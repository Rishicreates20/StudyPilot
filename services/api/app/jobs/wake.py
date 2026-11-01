"""Waking the worker: telling whatever runs jobs that there is work (ADR-052).

With ``JOB_WAKE=none`` (local development, Docker, a long-running worker anywhere) a worker process
polls the database, so waking does nothing. With ``JOB_WAKE=vercel_queue`` a message on Vercel
Queues invokes ``app.jobs.queue_consumer``, which runs jobs for a bounded time.

The message carries no data. The job is the row in ``generation_jobs``, which stays the only record
of what to do and is claimed with ``SKIP LOCKED``: a lost, late or repeated message can delay a job
but can never run it twice or change it.
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

import structlog

from app.core.config import JobWakeName, Settings

log = structlog.get_logger("app.jobs")

TOPIC = "studypilot-jobs"
# Vercel Queues accepts delays of up to seven days.
_MAX_DELAY_SECONDS = 7 * 24 * 3600.0
_SEND_ATTEMPTS = 2

type SendFunction = Callable[..., Awaitable[Any]]


class JobWake(Protocol):
    async def wake(self, *, delay_seconds: float = 0.0, key: str | None = None) -> None:
        """Ask for a run now (or after ``delay_seconds``). ``key`` deduplicates repeated asks."""
        ...


class NullWake:
    """A worker process polls the database: nothing to wake."""

    async def wake(self, *, delay_seconds: float = 0.0, key: str | None = None) -> None:
        return None


class VercelQueueWake:
    """Publishes an empty message on the jobs topic. Never raises: the job is already stored, and
    a failed wake only delays it until the next one (every run drains every runnable job)."""

    def __init__(self, send: SendFunction | None = None, *, retry_pause: float = 0.5) -> None:
        self._send = send
        self._retry_pause = retry_pause

    async def wake(self, *, delay_seconds: float = 0.0, key: str | None = None) -> None:
        send = self._send or _vercel_send()
        delay = min(max(0.0, delay_seconds), _MAX_DELAY_SECONDS)
        for attempt in range(1, _SEND_ATTEMPTS + 1):
            try:
                await send(TOPIC, {"wake": True}, delay=delay or None, idempotency_key=key)
            except Exception as error:
                log.warning(
                    "jobs.wake_failed",
                    attempt=attempt,
                    delay_seconds=round(delay),
                    error=type(error).__name__,
                )
                if attempt < _SEND_ATTEMPTS:
                    await asyncio.sleep(self._retry_pause)
            else:
                log.info("jobs.woken", delay_seconds=round(delay), deduplicated=key is not None)
                return


def _vercel_send() -> SendFunction:
    from vercel.queue import send  # imported here so nothing else needs the SDK loaded

    return send


def build_job_wake(settings: Settings) -> JobWake:
    if settings.job_wake is JobWakeName.VERCEL_QUEUE:
        return VercelQueueWake()
    return NullWake()
