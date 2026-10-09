import asyncio
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.config import AppEnv, Settings
from app.main import create_app
from support.database import create_auth_user, running_database
from support.keys import SigningKey, build_claims, make_ec_key, sign_with_key, static_jwks_fetcher
from support.settings import TEST_SUPABASE_URL, IsolatedSettings

_CONFIG_VARIABLES = (
    "APP_ENV",
    "APP_NAME",
    "APP_VERSION",
    "LOG_LEVEL",
    "CORS_ALLOWED_ORIGINS",
    "DATABASE_URL",
    "DB_POOL_MIN_SIZE",
    "DB_POOL_MAX_SIZE",
    "DB_POOL_TIMEOUT_SECONDS",
    "SUPABASE_URL",
    "SUPABASE_JWT_MODE",
    "SUPABASE_JWT_SECRET",
    "SUPABASE_JWT_AUDIENCE",
    "SUPABASE_JWT_ISSUER",
    "SUPABASE_JWKS_URL",
    "JWT_LEEWAY_SECONDS",
    "MAX_ACTIVE_GOALS_PER_USER",
)


@pytest.fixture(autouse=True)
def _isolated_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests must not depend on the developer's shell environment."""
    for name in _CONFIG_VARIABLES:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(scope="module")
def anyio_backend() -> tuple[str, dict[str, object]]:
    """Run async tests on a selector loop: psycopg's async mode rejects Windows' proactor loop."""
    return ("asyncio", {"loop_factory": asyncio.SelectorEventLoop})


def new_client(app: FastAPI) -> TestClient:
    # psycopg's async mode needs a selector event loop; Windows defaults to the proactor loop.
    return TestClient(
        app,
        raise_server_exceptions=False,
        backend_options={"loop_factory": asyncio.SelectorEventLoop},
    )


# --- Without a database: health, settings, error handling ---------------------------------------


@pytest.fixture
def settings() -> Settings:
    return IsolatedSettings(app_env=AppEnv.TEST)


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    # raise_server_exceptions=False: exercise the real 500 handler instead of re-raising.
    with new_client(app) as test_client:
        yield test_client


# --- With a real (PGlite) database and real signed tokens ---------------------------------------


@pytest.fixture(scope="session")
def database_dsn() -> Iterator[str]:
    """A PostgreSQL with the Supabase stub and every migration applied (one per test session)."""
    with running_database() as dsn:
        yield dsn


@pytest.fixture(scope="session")
def signing_key() -> SigningKey:
    return make_ec_key()


@pytest.fixture(scope="session")
def api_settings(database_dsn: str) -> Settings:
    return IsolatedSettings(
        app_env=AppEnv.TEST,
        database_url=SecretStr(database_dsn),
        supabase_url=TEST_SUPABASE_URL,
        db_pool_max_size=4,
    )


@pytest.fixture(scope="session")
def api_app(api_settings: Settings, signing_key: SigningKey) -> FastAPI:
    return create_app(api_settings, jwks_fetcher=static_jwks_fetcher(signing_key))


@pytest.fixture(scope="session")
def api(api_app: FastAPI) -> Iterator[TestClient]:
    """One application and connection pool for the whole session (see support/database.py)."""
    with new_client(api_app) as test_client:
        # Block until the pool's first connection is established, so no background connect
        # overlaps with the admin connection used by later tests.
        assert test_client.get("/readyz").status_code == 200
        yield test_client


@dataclass(frozen=True)
class Learner:
    """A real row in auth.users (and, via the trigger, public.profiles) plus a signed token."""

    id: UUID
    email: str
    token: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


@pytest.fixture
def make_learner(database_dsn: str, signing_key: SigningKey) -> Callable[..., Learner]:
    def factory(*, display_name: str | None = None) -> Learner:
        user_id = create_auth_user(database_dsn, display_name=display_name)
        email = f"{user_id}@example.test"
        claims = build_claims(sub=user_id, email=email)
        return Learner(id=user_id, email=email, token=sign_with_key(signing_key, claims))

    return factory
