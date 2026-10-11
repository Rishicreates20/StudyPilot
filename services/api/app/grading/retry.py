"""Asking for a short answer to be marked again after the grading job failed."""

from uuid import UUID

import structlog

from app.core.db import Database
from app.core.errors import ConflictError, NotFoundError

log = structlog.get_logger("app.grading")

# A learner can ask again a few times; after that the answer is theirs to review.
MAX_GRADING_JOBS_PER_ATTEMPT = 4


async def retry_grading(database: Database, *, user_id: UUID, attempt_id: UUID) -> UUID:
    """Queue a new grading job for an attempt that is waiting on one. Returns the job's id."""
    async with database.system_session() as connection:
        cursor = await connection.execute(
            "select a.id, a.status, r.goal_id, g.status as goal_status"
            " from public.quiz_attempts a"
            " join public.quizzes z on z.id = a.quiz_id and z.user_id = a.user_id"
            " join public.roadmaps r on r.id = z.roadmap_id and r.user_id = z.user_id"
            " join public.learning_goals g on g.id = r.goal_id and g.user_id = r.user_id"
            " where a.id = %s and a.user_id = %s for update of a",
            (attempt_id, user_id),
        )
        attempt = await cursor.fetchone()
        if attempt is None:
            raise NotFoundError("Attempt not found.", code="ATTEMPT_NOT_FOUND")
        if attempt["goal_status"] == "archived":
            raise ConflictError(
                "This goal is archived. Restore it to continue.", code="GOAL_ARCHIVED"
            )
        if attempt["status"] != "grading":
            raise ConflictError("Nothing is waiting to be marked.", code="NOT_GRADING")

        cursor = await connection.execute(
            "select count(*) filter (where status in ('queued', 'running')) as active,"
            " count(*) as total from public.generation_jobs"
            " where attempt_id = %s and user_id = %s",
            (attempt_id, user_id),
        )
        jobs = await cursor.fetchone()
        if jobs is None:
            raise RuntimeError("job count returned no row")
        if jobs["active"] > 0:
            raise ConflictError("Your answer is already being marked.", code="GRADING_ACTIVE")
        if jobs["total"] >= MAX_GRADING_JOBS_PER_ATTEMPT:
            raise ConflictError(
                "Marking has been tried several times. Mark your answer yourself against the "
                "model answer instead.",
                code="GRADING_RETRIES_EXHAUSTED",
            )
        cursor = await connection.execute(
            "insert into public.generation_jobs (user_id, goal_id, attempt_id, job_type)"
            " values (%s, %s, %s, 'grade') returning id",
            (user_id, attempt["goal_id"], attempt_id),
        )
        job = await cursor.fetchone()
        if job is None:
            raise RuntimeError("grading job insert returned no row")
        log.info("quiz.regrade_requested", attempt_id=str(attempt_id), job_id=str(job["id"]))
        return job["id"]
