from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, Response

from app.api.deps import DatabaseDep
from app.core.errors import ProblemDetail
from app.core.security import CurrentPrincipal
from app.schemas.jobs import GenerationJob
from app.schemas.lessons import LessonRequest, ProgressState, ProgressUpdate, StudyView
from app.services import lessons as lessons_service

router = APIRouter(tags=["lessons"])

_NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {"model": ProblemDetail, "description": "No such topic or lesson for this user"}
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
    "/roadmap-items/{item_id}/lessons",
    response_model=GenerationJob,
    status_code=202,
    summary="Start writing the lesson for a roadmap topic",
    responses={
        **_NOT_FOUND,
        **_CONFLICT,
        422: {"model": ProblemDetail, "description": "Revision sessions don't have lessons"},
        429: {"model": ProblemDetail, "description": "Too many lessons at once, or today's limit"},
        503: {"model": ProblemDetail, "description": "AI generation isn't configured"},
    },
)
async def start_lesson(
    item_id: UUID,
    payload: LessonRequest,
    request: Request,
    response: Response,
    principal: CurrentPrincipal,
    database: DatabaseDep,
    idempotency_key: IdempotencyKey = None,
) -> GenerationJob:
    """Queues a background job and returns it at once (202); poll `GET /v1/jobs/{id}`.

    Without a body a first lesson is written (409 if the topic already has one). With `adjust`,
    `feedback` or `regenerate`, a NEW version is written when the job completes: earlier versions
    are kept.
    """
    settings = request.app.state.settings
    async with database.user_transaction(principal) as connection:
        job = await lessons_service.start_generation(
            connection,
            principal,
            item_id,
            payload,
            idempotency_key=idempotency_key,
            settings=settings,
        )
    response.headers["Location"] = f"/v1/jobs/{job.id}"
    return job


@router.get(
    "/roadmap-items/{item_id}/study",
    response_model=StudyView,
    summary="Everything the study page needs for one topic",
    responses=_NOT_FOUND,
)
async def read_study(
    item_id: UUID,
    principal: CurrentPrincipal,
    database: DatabaseDep,
    lesson_id: Annotated[
        UUID | None, Query(description="Show this version instead of the current one.")
    ] = None,
) -> StudyView:
    """The topic, its lesson (current or the version asked for), the learner's progress, the
    newest lesson job, the neighbouring topics and the contents of the whole roadmap."""
    async with database.user_transaction(principal) as connection:
        return await lessons_service.get_study(connection, principal, item_id, lesson_id=lesson_id)


@router.put(
    "/lessons/{lesson_id}/progress",
    response_model=ProgressState,
    summary="Save the learner's place in a lesson",
    responses={**_NOT_FOUND, **_CONFLICT, 422: {"model": ProblemDetail}},
)
async def save_lesson_progress(
    lesson_id: UUID,
    payload: ProgressUpdate,
    principal: CurrentPrincipal,
    database: DatabaseDep,
) -> ProgressState:
    """Replaces the saved progress: which sections are done, where to resume, and whether the
    lesson is finished (which records every section as done). Not allowed on archived goals."""
    async with database.user_transaction(principal) as connection:
        return await lessons_service.save_progress(connection, principal, lesson_id, payload)
