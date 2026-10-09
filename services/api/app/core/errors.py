"""Error responses as RFC 9457 ``application/problem+json``.

Every error carries a stable machine-readable ``code`` and the request ID. Validation
errors list the offending fields and messages but never echo submitted values, and
unexpected errors return a generic body (no stack traces, prompts or secrets).
"""

from http import HTTPStatus
from typing import Any, cast

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
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    app.add_exception_handler(RequestValidationError, _validation_exception_handler)
    app.add_exception_handler(Exception, _unhandled_exception_handler)
