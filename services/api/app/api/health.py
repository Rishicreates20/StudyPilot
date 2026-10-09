"""Liveness and readiness probes. Unauthenticated; they expose no configuration."""

from collections.abc import Awaitable, Callable
from typing import Literal

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

router = APIRouter(tags=["health"])
log = structlog.get_logger("app.health")

ReadinessCheck = Callable[[], Awaitable[bool]]


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    version: str


class ReadinessResponse(BaseModel):
    status: Literal["ready", "unavailable"]
    checks: dict[str, Literal["ok", "fail"]]


@router.get("/healthz", response_model=HealthResponse, summary="Liveness probe")
async def healthz(request: Request) -> HealthResponse:
    """The process is up and able to serve requests. Does not touch dependencies."""
    settings = request.app.state.settings
    return HealthResponse(status="ok", service=settings.app_name, version=settings.app_version)


@router.get(
    "/readyz",
    response_model=ReadinessResponse,
    responses={503: {"model": ReadinessResponse, "description": "A dependency is unavailable"}},
    summary="Readiness probe",
)
async def readyz(request: Request) -> JSONResponse:
    """Run every registered dependency check; respond 503 if any fails.

    No dependencies exist yet, so with an empty registry the service is trivially ready.
    The database check is registered when persistence lands.
    """
    checks: dict[str, ReadinessCheck] = request.app.state.readiness_checks
    results: dict[str, Literal["ok", "fail"]] = {}
    for name, check in checks.items():
        try:
            results[name] = "ok" if await check() else "fail"
        except Exception:
            log.warning("readiness.check_failed", check=name, exc_info=True)
            results[name] = "fail"
    ready = all(value == "ok" for value in results.values())
    body = ReadinessResponse(status="ready" if ready else "unavailable", checks=results)
    return JSONResponse(body.model_dump(), status_code=200 if ready else 503)
