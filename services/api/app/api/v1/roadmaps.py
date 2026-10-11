from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, Response

from app.api.deps import DatabaseDep
from app.core.errors import ProblemDetail
from app.core.security import CurrentPrincipal
from app.schemas.roadmaps import (
    GenerationJob,
    JobList,
    Roadmap,
    RoadmapList,
    RoadmapRequest,
    RoadmapSummary,
)
from app.services import roadmaps as roadmaps_service

router = APIRouter(tags=["roadmaps"])

_NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {"model": ProblemDetail, "description": "No such goal, roadmap or job for this user"}
}
_CONFLICT: dict[int | str, dict[str, Any]] = {
    409: {"model": ProblemDetail, "description": "The request conflicts with the current state"}
}

IdempotencyKey = Annotated[
    str | None,
    Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=128,
        description="Send the same value when resubmitting a form: you get the same job back.",
    ),
]


@router.post(
    "/goals/{goal_id}/roadmaps",
    response_model=GenerationJob,
    status_code=202,
    summary="Start generating a roadmap for a goal",
    responses={
        **_NOT_FOUND,
        **_CONFLICT,
        422: {"model": ProblemDetail, "description": "The goal can't be planned yet"},
        429: {"model": ProblemDetail, "description": "Daily generation allowance used up"},
        503: {"model": ProblemDetail, "description": "AI generation isn't configured"},
    },
)
async def start_roadmap(
    goal_id: UUID,
    payload: RoadmapRequest,
    request: Request,
    response: Response,
    principal: CurrentPrincipal,
    database: DatabaseDep,
    idempotency_key: IdempotencyKey = None,
) -> GenerationJob:
    """Queues a background job and returns it at once (202); poll `GET /v1/jobs/{id}`.

    With `feedback`, the planner revises the current roadmap; without it, it makes a fresh plan.
    Either way a NEW version is stored when the job completes: earlier versions are kept.
    """
    settings = request.app.state.settings
    async with database.user_transaction(principal) as connection:
        job = await roadmaps_service.start_generation(
            connection,
            principal,
            goal_id,
            payload,
            idempotency_key=idempotency_key,
            settings=settings,
        )
    response.headers["Location"] = f"/v1/jobs/{job.id}"
    return job


@router.get(
    "/goals/{goal_id}/roadmaps",
    response_model=RoadmapList,
    summary="Every version of a goal's roadmap, newest first",
    responses=_NOT_FOUND,
)
async def list_roadmaps(
    goal_id: UUID, principal: CurrentPrincipal, database: DatabaseDep
) -> RoadmapList:
    async with database.user_transaction(principal) as connection:
        return await roadmaps_service.list_versions(connection, principal, goal_id)


@router.get(
    "/goals/{goal_id}/jobs",
    response_model=JobList,
    summary="A goal's recent generation jobs, newest first",
    responses=_NOT_FOUND,
)
async def list_goal_jobs(
    goal_id: UUID,
    principal: CurrentPrincipal,
    database: DatabaseDep,
    limit: Annotated[int, Query(ge=1, le=20)] = 5,
) -> JobList:
    async with database.user_transaction(principal) as connection:
        return await roadmaps_service.list_jobs(connection, principal, goal_id, limit=limit)


@router.get(
    "/roadmaps/{roadmap_id}",
    response_model=Roadmap,
    summary="One roadmap version with its modules, topics and schedule",
    responses=_NOT_FOUND,
)
async def read_roadmap(
    roadmap_id: UUID, principal: CurrentPrincipal, database: DatabaseDep
) -> Roadmap:
    async with database.user_transaction(principal) as connection:
        return await roadmaps_service.get_roadmap(connection, principal, roadmap_id)


@router.post(
    "/roadmaps/{roadmap_id}/make-current",
    response_model=RoadmapSummary,
    summary="Make this version the goal's current roadmap",
    responses={**_NOT_FOUND, **_CONFLICT},
)
async def make_roadmap_current(
    roadmap_id: UUID, principal: CurrentPrincipal, database: DatabaseDep
) -> RoadmapSummary:
    """Switches versions without deleting anything. Not allowed while the goal is archived."""
    async with database.user_transaction(principal) as connection:
        return await roadmaps_service.make_current(connection, principal, roadmap_id)


@router.get(
    "/jobs/{job_id}",
    response_model=GenerationJob,
    summary="The status of a generation job",
    responses=_NOT_FOUND,
)
async def read_job(
    job_id: UUID, principal: CurrentPrincipal, database: DatabaseDep
) -> GenerationJob:
    async with database.user_transaction(principal) as connection:
        return await roadmaps_service.get_job(connection, principal, job_id)


@router.post(
    "/jobs/{job_id}/cancel",
    response_model=GenerationJob,
    summary="Ask for a generation to stop",
    responses=_NOT_FOUND,
)
async def cancel_job(
    job_id: UUID, principal: CurrentPrincipal, database: DatabaseDep
) -> GenerationJob:
    """A job that hasn't started is cancelled at once; a running one stops at its next stage."""
    async with database.user_transaction(principal) as connection:
        return await roadmaps_service.cancel_job(connection, principal, job_id)


@router.post(
    "/jobs/{job_id}/retry",
    response_model=GenerationJob,
    status_code=202,
    summary="Retry a failed generation",
    responses={**_NOT_FOUND, **_CONFLICT},
)
async def retry_job(
    job_id: UUID,
    request: Request,
    response: Response,
    principal: CurrentPrincipal,
    database: DatabaseDep,
) -> GenerationJob:
    """Queues a new job that repeats the failed one; the failed job stays as history."""
    settings = request.app.state.settings
    async with database.user_transaction(principal) as connection:
        job = await roadmaps_service.retry_job(connection, principal, job_id, settings=settings)
    response.headers["Location"] = f"/v1/jobs/{job.id}"
    return job
