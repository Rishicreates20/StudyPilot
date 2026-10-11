"""Running one roadmap-generation job: load, plan, validate, store.

Stages (``generation_jobs.stage`` / ``progress``): loading 5 -> planning 20 -> validated 70 ->
saving 85 -> done 100. The validated plan is checkpointed before saving, so if storing it fails
and the job is retried, the (paid) model call is not repeated. Between stages the job checks that
it still owns its lease and that the learner has not cancelled.
"""

import asyncio
import random
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import date
from types import TracebackType
from typing import Self
from uuid import UUID

import structlog

from app.ai.provider import LLMError, LLMNotConfigured, LLMProvider
from app.ai.roadmap.context import build_context, readiness_problems
from app.ai.roadmap.planner import CallRecord, PlanInvalid, plan_roadmap
from app.core.config import Settings
from app.core.db import Database
from app.jobs import queue, store
from app.jobs.errors import JobCancelled, JobFailure, LeaseLost
from app.jobs.queue import Job
from app.schemas.goals import today_utc

log = structlog.get_logger("app.jobs")

_MAX_BACKOFF_SECONDS = 300.0
_MAX_FEEDBACK_CHARS = 500


@dataclass
class WorkerEnv:
    database: Database
    settings: Settings
    worker_id: str
    # None when no provider is configured: roadmap jobs then fail with AI_NOT_CONFIGURED.
    provider: LLMProvider | None
    today: Callable[[], date] = today_utc
    random: Callable[[], float] = field(default=random.random)


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


async def process_job(env: WorkerEnv, job: Job) -> None:
    """Run a claimed job to a final state (or back into the queue). Never raises for job errors."""
    async with Lease(env, job) as lease:
        try:
            await _run_roadmap(env, job, lease)
        except LeaseLost:
            log.warning("job.lease_lost", job_id=str(job.id))
        except JobCancelled:
            async with env.database.system_session() as connection:
                await queue.mark_cancelled(connection, job.id, env.worker_id)
            log.info("job.cancelled", job_id=str(job.id))
        except JobFailure as failure:
            await _end(env, job, failure.code, failure.message, retryable=failure.retryable)
        except PlanInvalid as invalid:
            log.info(
                "job.plan_invalid",
                job_id=str(job.id),
                violations=sorted({v.code for v in invalid.violations}),
            )
            await _end(env, job, invalid.code, invalid.user_message, retryable=False)
        except LLMError as error:
            log.warning(
                "job.model_error",
                job_id=str(job.id),
                code=error.code,
                retryable=error.retryable,
                detail=error.detail,
            )
            await _end(
                env,
                job,
                error.code,
                error.user_message,
                retryable=error.retryable,
                retry_after=error.retry_after,
            )
        except Exception:
            log.exception("job.unexpected_error", job_id=str(job.id))
            await _end(
                env, job, "INTERNAL_ERROR", "Something went wrong on our side.", retryable=True
            )


async def _end(
    env: WorkerEnv,
    job: Job,
    code: str,
    message: str,
    *,
    retryable: bool,
    retry_after: float | None = None,
) -> None:
    """Retry later if the failure is transient and attempts remain; otherwise fail for good."""
    async with env.database.system_session() as connection:
        if retryable and job.attempts < job.max_attempts:
            delay = backoff_seconds(
                job.attempts,
                env.settings.job_retry_base_seconds,
                jitter=env.random(),
                retry_after=retry_after,
            )
            await queue.retry_later(
                connection,
                job.id,
                env.worker_id,
                code=code,
                message=f"{message} Trying again shortly.",
                delay_seconds=delay,
            )
            log.info("job.retry_scheduled", job_id=str(job.id), code=code, in_seconds=round(delay))
            return
        suffix = " Please try again in a few minutes." if retryable else ""
        await queue.fail(connection, job.id, env.worker_id, code=code, message=message + suffix)
        log.info("job.failed", job_id=str(job.id), code=code)


async def _stage(env: WorkerEnv, job: Job, stage: str, progress: int) -> None:
    async with env.database.system_session() as connection:
        if not await queue.set_stage(connection, job.id, env.worker_id, stage, progress):
            raise LeaseLost


async def _run_roadmap(env: WorkerEnv, job: Job, lease: Lease) -> None:
    await _stage(env, job, "loading", 5)
    lease.check()
    async with env.database.system_session() as connection:
        goal = await store.load_goal(connection, job.user_id, job.goal_id)
    if goal is None:
        raise JobFailure("GOAL_UNAVAILABLE", "This goal no longer exists.")
    if goal.status == "archived":
        raise JobFailure(
            "GOAL_UNAVAILABLE", "This goal is archived. Restore it to generate a roadmap."
        )

    raw_feedback = job.request.get("feedback")
    feedback = (
        raw_feedback.strip()[:_MAX_FEEDBACK_CHARS] or None
        if isinstance(raw_feedback, str)
        else None
    )
    based_on = _as_uuid(job.request.get("base_roadmap_id"))
    if based_on is not None:
        async with env.database.system_session() as connection:
            based_on = await store.verify_base(connection, job.user_id, job.goal_id, based_on)

    if job.checkpoint:
        plan, meta = store.restore_checkpoint(job.checkpoint)
    else:
        problems = readiness_problems(goal, env.today())
        if problems:
            raise JobFailure("GOAL_NOT_PLANNABLE", problems[0])
        if env.provider is None:
            raise JobFailure("AI_NOT_CONFIGURED", LLMNotConfigured.user_message)
        await _stage(env, job, "planning", 20)

        outline = None
        if feedback and based_on is not None:
            async with env.database.system_session() as connection:
                outline = await store.load_outline(connection, job.user_id, based_on)
        context = build_context(
            goal, today=env.today(), feedback=feedback, previous_outline=outline
        )

        async def observe(record: CallRecord) -> None:
            async with env.database.system_session() as connection:
                await queue.record_usage(connection, job, record)

        outcome = await plan_roadmap(env.provider, context, observer=observe)
        lease.check()
        plan = outcome.plan
        meta = store.PlanMeta(
            prompt_version=outcome.prompt_version,
            provider=outcome.provider,
            model_id=outcome.model_id,
            synthetic=outcome.synthetic,
            total_minutes=outcome.metrics.total_minutes,
            total_days=outcome.metrics.total_days,
            topic_count=outcome.metrics.topic_count,
        )
        async with env.database.system_session() as connection:
            if not await queue.save_checkpoint(
                connection, job.id, env.worker_id, store.checkpoint_of(plan, meta)
            ):
                raise LeaseLost
        await _stage(env, job, "validated", 70)

    lease.check()
    await _stage(env, job, "saving", 85)
    async with env.database.system_session() as connection:
        saved = await store.save_roadmap(
            connection,
            job,
            env.worker_id,
            plan=plan,
            meta=meta,
            goal=goal,
            feedback=feedback,
            based_on=based_on,
        )
    log.info(
        "job.completed",
        job_id=str(job.id),
        roadmap_id=str(saved.id),
        version=saved.version,
        topics=meta.topic_count,
        synthetic=meta.synthetic,
    )


def _as_uuid(value: object) -> UUID | None:
    if not isinstance(value, str):
        return None
    try:
        return UUID(value)
    except ValueError:
        return None
