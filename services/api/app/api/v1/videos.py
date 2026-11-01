from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Header, Request, Response

from app.api.deps import DatabaseDep
from app.core.errors import ProblemDetail
from app.core.security import CurrentPrincipal
from app.schemas.jobs import GenerationJob
from app.schemas.videos import TopicVideos, VideoSearchRequest
from app.services import videos as videos_service

router = APIRouter(tags=["videos"])

_NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {"model": ProblemDetail, "description": "No such topic for this user"}
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


@router.get(
    "/roadmap-items/{item_id}/videos",
    response_model=TopicVideos,
    summary="A topic's suggested study videos",
    responses=_NOT_FOUND,
)
async def read_videos(
    item_id: UUID, request: Request, principal: CurrentPrincipal, database: DatabaseDep
) -> TopicVideos:
    """The videos found for a topic on YouTube, best match first, with the search they came from
    and the newest search job. Revision sessions have none (404)."""
    settings = request.app.state.settings
    async with database.user_transaction(principal) as connection:
        return await videos_service.get_videos(connection, principal, item_id, settings=settings)


@router.post(
    "/roadmap-items/{item_id}/videos",
    response_model=GenerationJob,
    status_code=202,
    summary="Find study videos for a topic",
    responses={
        **_NOT_FOUND,
        409: {
            "model": ProblemDetail,
            "description": "The request conflicts with the current state",
        },
        422: {"model": ProblemDetail, "description": "Revision sessions don't have videos"},
        429: {"model": ProblemDetail, "description": "Today's limit of video searches"},
        503: {"model": ProblemDetail, "description": "Video suggestions aren't configured"},
    },
)
async def start_video_search(
    item_id: UUID,
    payload: VideoSearchRequest,
    request: Request,
    response: Response,
    principal: CurrentPrincipal,
    database: DatabaseDep,
    idempotency_key: IdempotencyKey = None,
) -> GenerationJob:
    """Queues a background search and returns it at once (202); poll `GET /v1/jobs/{id}`.

    Without a body the topic's first search is made (409 if it already has suggestions). With
    `refresh`, a new search replaces the current suggestions when it finishes.
    """
    settings = request.app.state.settings
    async with database.user_transaction(principal) as connection:
        job = await videos_service.start_search(
            connection,
            principal,
            item_id,
            payload,
            idempotency_key=idempotency_key,
            settings=settings,
        )
    response.headers["Location"] = f"/v1/jobs/{job.id}"
    return job
