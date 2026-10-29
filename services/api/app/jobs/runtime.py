"""What every job needs while it runs: the worker's environment and a lease that stays alive.

A claimed job holds a lease that this worker keeps extending in the background. Between stages the
job calls ``Lease.check`` to find out whether it should stop (the learner cancelled, or another
worker owns the job now because this one was too slow).
"""

import asyncio
import random
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import date
from types import TracebackType
from typing import Self
from uuid import UUID

import structlog

from app.ai.provider import LLMProvider
from app.core.config import Settings
from app.core.db import Database
from app.documents.storage import DocumentFiles
from app.exports.files import ExportFiles
from app.jobs import queue
from app.jobs.errors import JobCancelled, LeaseLost
from app.jobs.queue import Job
from app.schemas.goals import today_utc

log = structlog.get_logger("app.jobs")

_MAX_BACKOFF_SECONDS = 300.0


@dataclass
class WorkerEnv:
    database: Database
    settings: Settings
    worker_id: str
    # None when no provider is configured: model jobs then fail with AI_NOT_CONFIGURED.
    provider: LLMProvider | None
    # Where uploaded files live; None when storage isn't configured (document jobs then fail).
    files: DocumentFiles | None = None
    # Where exported files go; None when storage isn't configured (export jobs then fail).
    export_files: ExportFiles | None = None
    today: Callable[[], date] = today_utc
    random: Callable[[], float] = field(default=random.random)
    # Waiting inside a job (for a rate limit to ease); tests replace it so they do not really wait.
    sleep: Callable[[float], Awaitable[None]] = field(default=asyncio.sleep)


def backoff_seconds(
    attempt: int, base: float, *, jitter: float, retry_after: float | None = None
) -> float:
    """Exponential backoff with jitter (``jitter`` in [0, 1)); never shorter than a retry hint."""
    delay = min(_MAX_BACKOFF_SECONDS, base * 2 ** max(0, attempt - 1)) * (0.5 + jitter)
    if retry_after is not None:
        delay = max(delay, min(retry_after, _MAX_BACKOFF_SECONDS))
    return delay


class Lease:
    """Keeps a claimed job's lease alive while the job runs, and notices a cancel request."""

    def __init__(self, env: WorkerEnv, job: Job) -> None:
        self._env = env
        self._job = job
        self._task: asyncio.Task[None] | None = None
        self.lost = False
        self.cancel_requested = job.cancel_requested

    async def __aenter__(self) -> Self:
        self._task = asyncio.create_task(self._beat())
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task

    def check(self) -> None:
        """Raise if this worker should stop working on the job."""
        if self.lost:
            raise LeaseLost
        if self.cancel_requested:
            raise JobCancelled

    async def _beat(self) -> None:
        settings = self._env.settings
        interval = max(0.5, settings.job_lease_seconds / 3)
        while True:
            await asyncio.sleep(interval)
            try:
                async with self._env.database.system_session() as connection:
                    state = await queue.heartbeat(
                        connection,
                        self._job.id,
                        self._env.worker_id,
                        lease_seconds=settings.job_lease_seconds,
                    )
            except Exception:  # a database hiccup: try again at the next beat
                log.warning("job.heartbeat_failed", job_id=str(self._job.id), exc_info=True)
                continue
            if state is None:
                self.lost = True
                return
            if state:
                self.cancel_requested = True


async def set_stage(env: WorkerEnv, job: Job, stage: str, progress: int) -> None:
    """Record where the job is for the progress display; raises ``LeaseLost`` if it isn't ours."""
    async with env.database.system_session() as connection:
        if not await queue.set_stage(connection, job.id, env.worker_id, stage, progress):
            raise LeaseLost


def as_uuid(value: object) -> UUID | None:
    """A UUID from a job-request value, or None. A job's request is data and may hold anything."""
    if not isinstance(value, str):
        return None
    try:
        return UUID(value)
    except ValueError:
        return None
