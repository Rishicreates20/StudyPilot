"""SQL for a learner's own generation jobs. Data access only; the rules live in the service.

Learners can read their jobs, create one, and raise the cancel flag. Everything else about a job
(claiming, progress, completion) is the worker's business and is not reachable from here: the
database grants forbid it.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from app.core.db import UserConnection
from app.schemas.jobs import GenerationJob, JobType

_SELECT = """
    select j.id, j.goal_id, j.item_id, j.attempt_id, j.document_id, j.export_id, j.job_type,
           j.status, j.stage, j.progress,
           j.attempts, j.max_attempts, j.cancel_requested, j.error_code, j.error_message,
           r.id as roadmap_id, l.id as lesson_id, z.id as quiz_id, j.created_at, j.started_at,
           j.finished_at
    from public.generation_jobs j
    left join public.roadmaps r on r.job_id = j.id
    left join public.lessons l on l.job_id = j.id
    left join public.quizzes z on z.job_id = j.id
"""


async def insert(
    connection: UserConnection,
    user_id: UUID,
    goal_id: UUID,
    *,
    idempotency_key: str | None,
    request: dict[str, Any],
    job_type: JobType = "roadmap",
    item_id: UUID | None = None,
    document_id: UUID | None = None,
    export_id: UUID | None = None,
) -> GenerationJob:
    cursor = await connection.execute(
        "insert into public.generation_jobs"
        " (user_id, goal_id, item_id, document_id, export_id, job_type, idempotency_key, request)"
        " values (%s, %s, %s, %s, %s, %s, %s, %s) returning id",
        (
            user_id,
            goal_id,
            item_id,
            document_id,
            export_id,
            job_type,
            idempotency_key,
            Jsonb(request),
        ),
    )
    row = await cursor.fetchone()
    if row is None:
        raise RuntimeError("insert returned no row")
    job = await get(connection, user_id, row["id"])
    if job is None:
        raise RuntimeError("the new job could not be read back")
    return job


async def get(connection: UserConnection, user_id: UUID, job_id: UUID) -> GenerationJob | None:
    cursor = await connection.execute(
        f"{_SELECT} where j.id = %s and j.user_id = %s",
        (job_id, user_id),
    )
    row = await cursor.fetchone()
    return GenerationJob.model_validate(row) if row else None


async def get_request(
    connection: UserConnection, user_id: UUID, job_id: UUID
) -> dict[str, Any] | None:
    """What the learner asked for when the job was created (feedback, adjustment, base)."""
    cursor = await connection.execute(
        "select request from public.generation_jobs where id = %s and user_id = %s",
        (job_id, user_id),
    )
    row = await cursor.fetchone()
    return dict(row["request"]) if row else None


async def find_by_idempotency_key(
    connection: UserConnection, user_id: UUID, key: str
) -> GenerationJob | None:
    cursor = await connection.execute(
        f"{_SELECT} where j.user_id = %s and j.idempotency_key = %s",
        (user_id, key),
    )
    row = await cursor.fetchone()
    return GenerationJob.model_validate(row) if row else None


async def active_for_goal(
    connection: UserConnection, user_id: UUID, goal_id: UUID
) -> GenerationJob | None:
    """The goal's roadmap job that is waiting or running, if any."""
    cursor = await connection.execute(
        f"{_SELECT} where j.user_id = %s and j.goal_id = %s and j.job_type = 'roadmap'"
        " and j.status in ('queued', 'running')",
        (user_id, goal_id),
    )
    row = await cursor.fetchone()
    return GenerationJob.model_validate(row) if row else None


async def active_for_item(
    connection: UserConnection, user_id: UUID, item_id: UUID, job_type: JobType
) -> GenerationJob | None:
    """The topic's job of this kind that is waiting or running, if any."""
    cursor = await connection.execute(
        f"{_SELECT} where j.user_id = %s and j.item_id = %s and j.job_type = %s"
        " and j.status in ('queued', 'running')",
        (user_id, item_id, job_type),
    )
    row = await cursor.fetchone()
    return GenerationJob.model_validate(row) if row else None


async def latest_for_item(
    connection: UserConnection, user_id: UUID, item_id: UUID, job_type: JobType
) -> GenerationJob | None:
    """The newest job of this kind for a topic, whatever its state."""
    cursor = await connection.execute(
        f"{_SELECT} where j.user_id = %s and j.item_id = %s and j.job_type = %s"
        " order by j.created_at desc, j.id desc limit 1",
        (user_id, item_id, job_type),
    )
    row = await cursor.fetchone()
    return GenerationJob.model_validate(row) if row else None


async def latest_for_document(
    connection: UserConnection, user_id: UUID, document_id: UUID
) -> GenerationJob | None:
    """The newest processing job of a document, whatever its state."""
    cursor = await connection.execute(
        f"{_SELECT} where j.user_id = %s and j.document_id = %s"
        " order by j.created_at desc, j.id desc limit 1",
        (user_id, document_id),
    )
    row = await cursor.fetchone()
    return GenerationJob.model_validate(row) if row else None


async def latest_per_document(
    connection: UserConnection, user_id: UUID, goal_id: UUID
) -> dict[UUID, GenerationJob]:
    """The newest processing job of every document of a goal, by document id."""
    cursor = await connection.execute(
        "select distinct on (document_id) id from public.generation_jobs"
        " where user_id = %s and goal_id = %s and document_id is not null"
        " order by document_id, created_at desc, id desc",
        (user_id, goal_id),
    )
    ids = [row["id"] for row in await cursor.fetchall()]
    if not ids:
        return {}
    cursor = await connection.execute(
        f"{_SELECT} where j.user_id = %s and j.id = any(%s)", (user_id, ids)
    )
    jobs = [GenerationJob.model_validate(row) for row in await cursor.fetchall()]
    return {job.document_id: job for job in jobs if job.document_id is not None}


async def latest_for_export(
    connection: UserConnection, user_id: UUID, export_id: UUID
) -> GenerationJob | None:
    """The newest job of an export, whatever its state."""
    cursor = await connection.execute(
        f"{_SELECT} where j.user_id = %s and j.export_id = %s"
        " order by j.created_at desc, j.id desc limit 1",
        (user_id, export_id),
    )
    row = await cursor.fetchone()
    return GenerationJob.model_validate(row) if row else None


async def latest_per_export(
    connection: UserConnection, user_id: UUID, goal_id: UUID
) -> dict[UUID, GenerationJob]:
    """The newest job of every export of a goal, by export id."""
    cursor = await connection.execute(
        "select distinct on (export_id) id from public.generation_jobs"
        " where user_id = %s and goal_id = %s and export_id is not null"
        " order by export_id, created_at desc, id desc",
        (user_id, goal_id),
    )
    ids = [row["id"] for row in await cursor.fetchall()]
    if not ids:
        return {}
    cursor = await connection.execute(
        f"{_SELECT} where j.user_id = %s and j.id = any(%s)", (user_id, ids)
    )
    jobs = [GenerationJob.model_validate(row) for row in await cursor.fetchall()]
    return {job.export_id: job for job in jobs if job.export_id is not None}


async def latest_for_attempt(
    connection: UserConnection, user_id: UUID, attempt_id: UUID
) -> GenerationJob | None:
    """The newest marking job of a quiz attempt, whatever its state."""
    cursor = await connection.execute(
        f"{_SELECT} where j.user_id = %s and j.attempt_id = %s"
        " order by j.created_at desc, j.id desc limit 1",
        (user_id, attempt_id),
    )
    row = await cursor.fetchone()
    return GenerationJob.model_validate(row) if row else None


async def list_for_goal(
    connection: UserConnection, user_id: UUID, goal_id: UUID, *, limit: int
) -> list[GenerationJob]:
    """A goal's roadmap jobs, newest first (lesson jobs are listed per topic)."""
    cursor = await connection.execute(
        f"{_SELECT} where j.user_id = %s and j.goal_id = %s and j.job_type = 'roadmap'"
        " order by j.created_at desc, j.id desc limit %s",
        (user_id, goal_id, limit),
    )
    return [GenerationJob.model_validate(row) for row in await cursor.fetchall()]


async def count_since(
    connection: UserConnection, user_id: UUID, since: datetime, job_type: JobType = "roadmap"
) -> int:
    cursor = await connection.execute(
        "select count(*) as total from public.generation_jobs"
        " where user_id = %s and job_type = %s and created_at >= %s",
        (user_id, job_type, since),
    )
    row = await cursor.fetchone()
    return int(row["total"]) if row else 0


async def count_active_lessons(connection: UserConnection, user_id: UUID) -> int:
    """Lesson jobs this learner has waiting or running right now."""
    cursor = await connection.execute(
        "select count(*) as total from public.generation_jobs"
        " where user_id = %s and job_type = 'lesson' and status in ('queued', 'running')",
        (user_id,),
    )
    row = await cursor.fetchone()
    return int(row["total"]) if row else 0


async def request_cancel(connection: UserConnection, user_id: UUID, job_id: UUID) -> None:
    """Raise the cancel flag. A job that has not started is cancelled at once by the database."""
    await connection.execute(
        "update public.generation_jobs set cancel_requested = true"
        " where id = %s and user_id = %s and status in ('queued', 'running')",
        (job_id, user_id),
    )
