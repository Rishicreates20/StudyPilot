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
from app.schemas.roadmaps import GenerationJob

_SELECT = """
    select j.id, j.goal_id, j.job_type, j.status, j.stage, j.progress, j.attempts, j.max_attempts,
           j.cancel_requested, j.error_code, j.error_message, r.id as roadmap_id, j.created_at,
           j.started_at, j.finished_at
    from public.generation_jobs j
    left join public.roadmaps r on r.job_id = j.id
"""


async def insert(
    connection: UserConnection,
    user_id: UUID,
    goal_id: UUID,
    *,
    idempotency_key: str | None,
    request: dict[str, Any],
) -> GenerationJob:
    cursor = await connection.execute(
        "insert into public.generation_jobs (user_id, goal_id, job_type, idempotency_key, request)"
        " values (%s, %s, 'roadmap', %s, %s) returning id",
        (user_id, goal_id, idempotency_key, Jsonb(request)),
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
    """What the learner asked for when the job was created (feedback and the base roadmap)."""
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
    cursor = await connection.execute(
        f"{_SELECT} where j.user_id = %s and j.goal_id = %s and j.status in ('queued', 'running')",
        (user_id, goal_id),
    )
    row = await cursor.fetchone()
    return GenerationJob.model_validate(row) if row else None


async def list_for_goal(
    connection: UserConnection, user_id: UUID, goal_id: UUID, *, limit: int
) -> list[GenerationJob]:
    """Newest first."""
    cursor = await connection.execute(
        f"{_SELECT} where j.user_id = %s and j.goal_id = %s"
        " order by j.created_at desc, j.id desc limit %s",
        (user_id, goal_id, limit),
    )
    return [GenerationJob.model_validate(row) for row in await cursor.fetchall()]


async def count_since(connection: UserConnection, user_id: UUID, since: datetime) -> int:
    cursor = await connection.execute(
        "select count(*) as total from public.generation_jobs"
        " where user_id = %s and created_at >= %s",
        (user_id, since),
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
