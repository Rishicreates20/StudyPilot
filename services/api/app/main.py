"""ASGI application factory.

Run with ``uvicorn app.main:create_app --factory`` so importing this module has no side
effects: settings are validated and logging configured only when the app is created.
"""

from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, asynccontextmanager

import httpx2
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health
from app.api import v1 as api_v1
from app.core.config import Settings, load_settings_or_exit
from app.core.db import Database
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.request_context import REQUEST_ID_HEADER, RequestContextMiddleware
from app.core.security import HttpJwksFetcher, JwksFetcher, TokenVerifier

_JWKS_HTTP_TIMEOUT_SECONDS = 3.0


def create_app(
    settings: Settings | None = None, *, jwks_fetcher: JwksFetcher | None = None
) -> FastAPI:
    """Build the application.

    ``jwks_fetcher`` replaces the HTTP fetch of the project's signing keys. Tests use it to serve
    the public half of a locally generated key pair; tokens are still verified with real
    cryptography exactly as in production.
    """
    settings = settings or load_settings_or_exit()
    configure_logging(settings.log_level, json_logs=settings.json_logs)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        async with AsyncExitStack() as stack:
            fetcher = jwks_fetcher
            if fetcher is None and settings.jwks_url is not None:
                client = httpx2.AsyncClient(timeout=_JWKS_HTTP_TIMEOUT_SECONDS)
                stack.push_async_callback(client.aclose)
                fetcher = HttpJwksFetcher(client, settings.jwks_url)
            app.state.token_verifier = TokenVerifier.from_settings(settings, fetcher=fetcher)

            if settings.database_url is not None:
                database = Database.from_settings(settings)
                await database.open()
                stack.push_async_callback(database.close)
                app.state.database = database
                app.state.readiness_checks["database"] = database.ping
            yield

    app = FastAPI(
        title=f"{settings.app_name} API",
        version=settings.app_version,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.readiness_checks = {}
    app.state.database = None
    app.state.token_verifier = None

    # Added first = inner. Bearer tokens (not cookies) authenticate the API, so credentials
    # are not allowed cross-origin.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", REQUEST_ID_HEADER],
        expose_headers=[REQUEST_ID_HEADER],
        max_age=600,
    )
    # Added last = outermost, so preflight responses and CORS rejections are also correlated.
    app.add_middleware(RequestContextMiddleware)

    register_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(api_v1.router)
    return app
