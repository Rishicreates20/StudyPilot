"""The PostgreSQL job queue, worker side (ADR-003).

Claiming uses ``FOR UPDATE SKIP LOCKED`` so concurrent workers never take the same job. A claimed
job holds a lease (``locked_until``) that the worker keeps extending while it works; a job whose
lease runs out (the worker died) is put back in the queue, or failed once its attempts are used up.
Every write after the claim is conditional on ``locked_by = <this worker>`` and
``status = 'running'``, so a worker that was presumed dead and replaced cannot overwrite the new
owner's work.

These functions use the privileged ``SystemConnection`` and are for the worker only.
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from app.ai.calls import CallRecord
from app.core.db import SystemConnection

_JOB_COLUMNS = (
    "id, user_id, goal_id, item_id, attempt_id, document_id, job_type, attempts, max_attempts,"
    " request, checkpoint, cancel_requested"
)


@dataclass(frozen=True)
class Job:
    id: UUID
    user_id: UUID
    goal_id: UUID
    # The roadmap item a lesson job writes for; None for roadmap jobs.
    item_id: UUID | None
    # The quiz attempt a grading job marks; None for every other kind of job.
    attempt_id: UUID | None
    # The document a document job processes; None for every other kind of job.
    document_id: UUID | None
    job_type: str
    attempts: int
    max_attempts: int
    request: dict[str, Any]
    checkpoint: dict[str, Any] | None
    cancel_requested: bool


def _job(row: dict[str, Any]) -> Job:
    return Job(
        id=row["id"],
        user_id=row["user_id"],
        goal_id=row["goal_id"],
        item_id=row["item_id"],
        attempt_id=row["attempt_id"],
        document_id=row["document_id"],
        job_type=row["job_type"],
        attempts=row["attempts"],
        max_attempts=row["max_attempts"],
        request=row["request"] or {},
        checkpoint=row["checkpoint"],
        cancel_requested=row["cancel_requested"],
    )


async def claim_next(
    connection: SystemConnection, *, worker_id: str, lease_seconds: int, max_attempts: int
) -> Job | None:
    """Take the oldest runnable job, or None if there isn't one."""
    cursor = await connection.execute(
        f"""
        update public.generation_jobs set
            status = 'running',
            stage = 'starting',
            attempts = attempts + 1,
            max_attempts = %(max_attempts)s,
            locked_by = %(worker)s,
            locked_until = now() + %(lease)s * interval '1 second',
            started_at = coalesce(started_at, now()),
            error_code = null,
            error_message = null
        where id = (
            select id from public.generation_jobs
            where status = 'queued' and run_at <= now()
            order by run_at, created_at
            for update skip locked
            limit 1
        )
        returning {_JOB_COLUMNS}
        """,  # noqa: S608 - _JOB_COLUMNS is a module constant
        {"worker": worker_id, "lease": lease_seconds, "max_attempts": max_attempts},
    )
    row = await cursor.fetchone()
    return _job(row) if row else None


async def heartbeat(
    connection: SystemConnection, job_id: UUID, worker_id: str, *, lease_seconds: int
) -> bool | None:
    """Extend the lease. Returns whether a cancel was requested, or None if the lease is lost."""
    cursor = await connection.execute(
        "update public.generation_jobs set locked_until = now() + %s * interval '1 second'"
        " where id = %s and locked_by = %s and status = 'running' returning cancel_requested",
        (lease_seconds, job_id, worker_id),
    )
    row = await cursor.fetchone()
    return None if row is None else bool(row["cancel_requested"])


async def set_stage(
    connection: SystemConnection, job_id: UUID, worker_id: str, stage: str, progress: int
) -> bool:
    cursor = await connection.execute(
        "update public.generation_jobs set stage = %s, progress = %s"
        " where id = %s and locked_by = %s and status = 'running'",
        (stage, progress, job_id, worker_id),
    )
    return cursor.rowcount == 1


async def save_checkpoint(
    connection: SystemConnection, job_id: UUID, worker_id: str, checkpoint: dict[str, Any]
) -> bool:
    cursor = await connection.execute(
        "update public.generation_jobs set checkpoint = %s"
        " where id = %s and locked_by = %s and status = 'running'",
        (Jsonb(checkpoint), job_id, worker_id),
    )
    return cursor.rowcount == 1


async def complete(connection: SystemConnection, job_id: UUID, worker_id: str) -> bool:
    cursor = await connection.execute(
        "update public.generation_jobs set status = 'completed', stage = 'done', progress = 100,"
        " locked_by = null, locked_until = null, finished_at = now(),"
        " error_code = null, error_message = null"
        " where id = %s and locked_by = %s and status = 'running'",
        (job_id, worker_id),
    )
    return cursor.rowcount == 1


async def fail(
    connection: SystemConnection, job_id: UUID, worker_id: str, *, code: str, message: str
) -> bool:
    """End the job for good, with a reason the learner can read."""
    cursor = await connection.execute(
        "update public.generation_jobs set status = 'failed', stage = 'failed',"
        " locked_by = null, locked_until = null, finished_at = now(),"
        " error_code = %s, error_message = %s"
        " where id = %s and locked_by = %s and status = 'running'",
        (code, message[:500], job_id, worker_id),
    )
    return cursor.rowcount == 1


async def retry_later(
    connection: SystemConnection,
    job_id: UUID,
    worker_id: str,
    *,
    code: str,
    message: str,
    delay_seconds: float,
) -> bool:
    """Put the job back in the queue to run again after ``delay_seconds``."""
    cursor = await connection.execute(
        "update public.generation_jobs set status = 'queued', stage = 'waiting_retry',"
        " locked_by = null, locked_until = null,"
        " run_at = now() + %s * interval '1 second', error_code = %s, error_message = %s"
        " where id = %s and locked_by = %s and status = 'running'",
        (delay_seconds, code, message[:500], job_id, worker_id),
    )
    return cursor.rowcount == 1


async def mark_cancelled(connection: SystemConnection, job_id: UUID, worker_id: str) -> bool:
    cursor = await connection.execute(
        "update public.generation_jobs set status = 'cancelled', stage = 'cancelled',"
        " locked_by = null, locked_until = null, finished_at = now()"
        " where id = %s and locked_by = %s and status = 'running'",
        (job_id, worker_id),
    )
    return cursor.rowcount == 1


async def reap_expired(connection: SystemConnection) -> list[UUID]:
    """Recover jobs whose worker vanished: cancel, requeue or fail them. Returns their ids."""
    cursor = await connection.execute(
        """
        update public.generation_jobs set
            status = case when cancel_requested then 'cancelled'
                          when attempts >= max_attempts then 'failed'
                          else 'queued' end,
            stage = case when cancel_requested then 'cancelled'
                         when attempts >= max_attempts then 'failed'
                         else 'waiting_retry' end,
            locked_by = null,
            locked_until = null,
            run_at = case when cancel_requested or attempts >= max_attempts then run_at
                          else now() end,
            finished_at = case when cancel_requested or attempts >= max_attempts then now() end,
            error_code = case when cancel_requested then null else 'WORKER_LOST' end,
            error_message = case when cancel_requested then null
                else 'The worker stopped before finishing this job.' end
        where status = 'running' and locked_until < now()
        returning id
        """
    )
    return [row["id"] for row in await cursor.fetchall()]


async def record_usage(connection: SystemConnection, job: Job, record: CallRecord) -> None:
    await connection.execute(
        "insert into public.ai_usage_events (user_id, job_id, purpose, provider, model_id,"
        " prompt_version, input_tokens, output_tokens, latency_ms, finish_reason, error_code)"
        " values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            job.user_id,
            job.id,
            record.purpose,
            record.provider,
            record.model_id,
            record.prompt_version,
            record.input_tokens,
            record.output_tokens,
            record.latency_ms,
            record.finish_reason,
            record.error_code,
        ),
    )
