"""Error responses as RFC 9457 ``application/problem+json``.

Every error carries a stable machine-readable ``code`` and the request ID. Validation
errors list the offending fields and messages but never echo submitted values, and
unexpected errors return a generic body (no stack traces, prompts or secrets).
"""

from http import HTTPStatus
from typing import Any, cast

import psycopg
import psycopg.errors
import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.request_context import REQUEST_ID_HEADER, request_id_from_scope

PROBLEM_JSON = "application/problem+json"

_CODES_BY_STATUS: dict[int, str] = {
    400: "BAD_REQUEST",
    401: "UNAUTHENTICATED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
}

log = structlog.get_logger("app.errors")


class FieldError(BaseModel):
    field: str
    message: str
    code: str


class ProblemDetail(BaseModel):
    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    code: str
    request_id: str | None = None
    errors: list[FieldError] | None = None


class AppError(Exception):
    """A deliberate, user-safe failure. Subclasses fix the HTTP status and default code."""

    status_code: int = 500
    code: str = "INTERNAL_ERROR"

    def __init__(
        self,
        detail: str | None = None,
        *,
        code: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(detail or self.code)
        self.detail = detail
        self.code = code or type(self).code
        self.headers = headers or {}


class AuthenticationError(AppError):
    status_code = 401
    code = "UNAUTHENTICATED"

    def __init__(
        self,
        detail: str | None = None,
        *,
        code: str | None = None,
        www_authenticate: str = "Bearer",
    ) -> None:
        super().__init__(detail, code=code, headers={"WWW-Authenticate": www_authenticate})


class NotFoundError(AppError):
    status_code = 404
    code = "NOT_FOUND"


class ConflictError(AppError):
    status_code = 409
    code = "CONFLICT"


class InvalidRequestError(AppError):
    status_code = 422
    code = "INVALID_REQUEST"


class ServiceUnavailableError(AppError):
    status_code = 503
    code = "SERVICE_UNAVAILABLE"


def problem_response(
    request: Request,
    *,
    status: int,
    code: str,
    detail: str | None = None,
    errors: list[FieldError] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    request_id = request_id_from_scope(request.scope)
    body = ProblemDetail(
        title=HTTPStatus(status).phrase,
        status=status,
        detail=detail,
        code=code,
        request_id=request_id,
        errors=errors,
    )
    response_headers = dict(headers or {})
    if request_id:
        response_headers[REQUEST_ID_HEADER] = request_id
    return JSONResponse(
        body.model_dump(exclude_none=True),
        status_code=status,
        media_type=PROBLEM_JSON,
        headers=response_headers,
    )


async def _app_error_handler(request: Request, exc: Exception) -> JSONResponse:
    app_error = cast(AppError, exc)  # registered for exactly this type
    return problem_response(
        request,
        status=app_error.status_code,
        code=app_error.code,
        detail=app_error.detail,
        headers=app_error.headers,
    )


async def _http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    http_error = cast(StarletteHTTPException, exc)  # registered for exactly this type
    code = _CODES_BY_STATUS.get(http_error.status_code, f"HTTP_{http_error.status_code}")
    # FastAPI's HTTPException allows any JSON as detail; only plain strings are surfaced.
    detail = http_error.detail if isinstance(http_error.detail, str) else None  # pyright: ignore[reportUnnecessaryIsInstance]
    return problem_response(
        request,
        status=http_error.status_code,
        code=code,
        detail=detail,
        headers=dict(http_error.headers) if http_error.headers else None,
    )


async def _validation_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    validation_error = cast(RequestValidationError, exc)  # registered for exactly this type
    errors: list[FieldError] = []
    for item in validation_error.errors():
        location: Any = item.get("loc", ())
        errors.append(
            FieldError(
                field=".".join(str(part) for part in location),
                message=str(item.get("msg", "Invalid value")),
                code=str(item.get("type", "invalid")),
            )
        )
    return problem_response(
        request,
        status=422,
        code="VALIDATION_ERROR",
        detail="The request contains invalid data.",
        errors=errors,
    )


async def _database_unavailable_handler(request: Request, exc: Exception) -> JSONResponse:
    # Connection failures, pool exhaustion and timeouts. The driver message can name hosts and
    # users, so only the exception type is logged and nothing is returned to the caller.
    log.error("database.unavailable", error_type=type(exc).__name__)
    return problem_response(
        request,
        status=503,
        code="SERVICE_UNAVAILABLE",
        detail="The service is temporarily unavailable. Please try again shortly.",
        headers={"Retry-After": "5"},
    )


async def _permission_denied_handler(request: Request, exc: Exception) -> JSONResponse:
    # Postgres refused the operation (an RLS policy or a missing grant). The API should never
    # attempt this for a legitimate request, so treat it as a security event.
    log.warning(
        "security.database_permission_denied",
        error_type=type(exc).__name__,
        sqlstate=getattr(exc, "sqlstate", None),
    )
    return problem_response(
        request,
        status=403,
        code="FORBIDDEN",
        detail="You do not have permission to do that.",
    )


async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = request_id_from_scope(request.scope)
    log.error("request.unhandled_exception", request_id=request_id, exc_info=exc)
    return problem_response(
        request,
        status=500,
        code="INTERNAL_ERROR",
        detail="Something went wrong on our side. Quote the request ID if you contact support.",
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error_handler)
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    app.add_exception_handler(RequestValidationError, _validation_exception_handler)
    app.add_exception_handler(psycopg.OperationalError, _database_unavailable_handler)
    app.add_exception_handler(psycopg.errors.InsufficientPrivilege, _permission_denied_handler)
    app.add_exception_handler(Exception, _unhandled_exception_handler)
