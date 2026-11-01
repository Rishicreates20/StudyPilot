"""The Vercel Queues consumer that runs jobs (ADR-052).

Declared under ``[[tool.vercel.subscribers]]`` in ``pyproject.toml``. At build time Vercel imports
this module, reads the ``@subscribe`` configuration and generates a private, queue-triggered
function: it has no public URL, and only Vercel Queues can invoke it.

Each message is a wake-up call with no data. The handler runs the worker for a bounded time
(``app.jobs.drain``) and asks for the next run if work is left. Returning acknowledges the message.
If the run fails before it can finish (the database is unreachable, the settings are wrong), the
message is retried a minute later. If the platform stops the function at its time limit, the
message was never acknowledged, so Vercel delivers it again, and that run's first step recovers
the job that was cut off.
"""

import structlog
from vercel.queue import Message, RetryAfter, subscribe

from app.core.config import Settings
from app.core.logging import configure_logging
from app.jobs.drain import DrainResult, drain, follow_up
from app.jobs.environment import worker_environment
from app.jobs.wake import TOPIC, JobWake, VercelQueueWake

log = structlog.get_logger("app.worker")

_RETRY_AFTER_SECONDS = 60


async def run_bounded(settings: Settings, wake: JobWake) -> DrainResult:
    async with worker_environment(settings) as env:
        result = await drain(env, budget_seconds=settings.job_drain_seconds)
        await follow_up(env, wake)
        return result


# One consumer group, so each wake-up starts one run. Two runs at a time at most: jobs are claimed
# with SKIP LOCKED, so runs never share a job, and the cap keeps database connections and model
# calls within free-tier limits.
@subscribe(
    topic=TOPIC,
    consumer_group="job-runner",
    retry_after=_RETRY_AFTER_SECONDS,
    max_concurrency=2,
)
async def run_jobs(message: Message[dict[str, object]]) -> None:
    try:
        settings = Settings()
        configure_logging(settings.log_level, json_logs=settings.json_logs)
        await run_bounded(settings, VercelQueueWake())
    except Exception as error:
        log.exception(
            "worker.run_failed",
            delivery=message.metadata.delivery_count,
            error=type(error).__name__,
        )
        raise RetryAfter(_RETRY_AFTER_SECONDS) from error
