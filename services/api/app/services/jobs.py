"""Following, cancelling and retrying a learner's generation jobs, whatever kind they are."""

from uuid import UUID

import structlog

from app.core.config import Settings
from app.core.db import UserConnection
from app.core.errors import ConflictError, NotFoundError
from app.core.security import Principal
from app.repositories import jobs as jobs_repo
from app.schemas.jobs import GenerationJob
from app.schemas.roadmaps import RoadmapRequest
from app.services import lessons as lessons_service
from app.services import roadmaps as roadmaps_service

log = structlog.get_logger("app.jobs")

_FINISHED = frozenset({"completed", "failed", "cancelled"})


async def get_job(connection: UserConnection, principal: Principal, job_id: UUID) -> GenerationJob:
    job = await jobs_repo.get(connection, principal.user_id, job_id)
    if job is None:
        # Same answer for "does not exist" and "belongs to someone else".
        raise NotFoundError("Job not found.", code="JOB_NOT_FOUND")
    return job


async def cancel_job(
    connection: UserConnection, principal: Principal, job_id: UUID
) -> GenerationJob:
    """Ask for a job to stop. Cancelling a finished job changes nothing."""
    job = await get_job(connection, principal, job_id)
    if job.status in _FINISHED:
        return job
    await jobs_repo.request_cancel(connection, principal.user_id, job_id)
    log.info("job.cancel_requested", job_id=str(job_id), job_type=job.job_type)
    return await get_job(connection, principal, job_id)


async def retry_job(
    connection: UserConnection, principal: Principal, job_id: UUID, *, settings: Settings
) -> GenerationJob:
    """Queue a fresh job repeating a failed one. The failed job stays as history."""
    job = await get_job(connection, principal, job_id)
    if job.status != "failed":
        raise ConflictError(
            "Only a generation that failed can be retried.", code="JOB_NOT_RETRYABLE"
        )
    if job.job_type == "lesson":
        return await lessons_service.retry_job(connection, principal, job, settings=settings)
    request = await jobs_repo.get_request(connection, principal.user_id, job_id) or {}
    feedback = request.get("feedback")
    return await roadmaps_service.start_generation(
        connection,
        principal,
        job.goal_id,
        RoadmapRequest(feedback=feedback if isinstance(feedback, str) else None),
        idempotency_key=None,
        settings=settings,
    )
