"""Request correlation: assign/propagate ``X-Request-ID`` and log each request once.

Implemented as a plain ASGI middleware (not ``BaseHTTPMiddleware``) so it adds no
per-request task overhead and does not interfere with streaming responses.
"""

import re
import time
import uuid

import structlog
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-ID"
# Accept a caller-supplied ID only if it is short and boring; otherwise generate our own.
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")

log = structlog.get_logger("app.request")


def request_id_from_scope(scope: Scope) -> str | None:
    state = scope.get("state")
    if isinstance(state, dict):
        value = state.get("request_id")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        return value if isinstance(value, str) else None
    return None


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        supplied = Headers(scope=scope).get(REQUEST_ID_HEADER)
        request_id = supplied if supplied and _SAFE_REQUEST_ID.match(supplied) else uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        status_code = 500
        started = time.perf_counter()

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            log.info(
                "request.completed",
                method=scope["method"],
                path=scope["path"],
                status=status_code,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
