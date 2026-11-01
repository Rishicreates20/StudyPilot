"""Business rules for finding study videos for a topic (ADR-051).

The API never calls YouTube. Asking for videos only validates the request and queues a
``resources`` job in the caller's own transaction; the worker searches, checks and ranks, and is
the only writer of the suggestion tables. The YouTube quota belongs to the whole server, so on top
of the per-learner allowance here the worker keeps a daily ledger and stops at its limit.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import psycopg.errors
import structlog

from app.core.config import Settings
from app.core.db import UserConnection
from app.core.errors import (
    ConflictError,
    InvalidRequestError,
    NotFoundError,
    RateLimitedError,
    ServiceUnavailableError,
)
from app.core.security import Principal
from app.repositories import goals as goals_repo
from app.repositories import jobs as jobs_repo
from app.repositories import lessons as lessons_repo
from app.repositories import videos as videos_repo
from app.schemas.jobs import GenerationJob
from app.schemas.videos import TopicVideos, VideoSearchRequest

log = structlog.get_logger("app.videos")

_ALLOWANCE_WINDOW = timedelta(hours=24)


def _topic_not_found() -> NotFoundError:
    # Same answer for "does not exist", "belongs to someone else" and "is a revision session".
    return NotFoundError("Topic not found.", code="TOPIC_NOT_FOUND")


async def get_videos(
    connection: UserConnection, principal: Principal, item_id: UUID, *, settings: Settings
) -> TopicVideos:
    """A topic's suggested videos, the search behind them and the newest search job."""
    record = await lessons_repo.get_topic(connection, principal.user_id, item_id)
    if record is None or record.topic.kind == "revision":
        raise _topic_not_found()
    search = await videos_repo.get_search(connection, principal.user_id, item_id)
    videos = await videos_repo.list_videos(connection, principal.user_id, item_id) if search else []
    job = await jobs_repo.latest_for_item(connection, principal.user_id, item_id, "resources")
    return TopicVideos(
        item_id=item_id,
        configured=settings.videos_configured,
        can_search=settings.videos_configured
        and record.roadmap.status == "current"
        and record.goal_status != "archived",
        search=search,
        videos=videos,
        job=job,
    )


async def start_search(
    connection: UserConnection,
    principal: Principal,
    item_id: UUID,
    payload: VideoSearchRequest,
    *,
    idempotency_key: str | None,
    settings: Settings,
) -> GenerationJob:
    """Queue a video search for one topic of the caller's current roadmap."""
    if not settings.videos_configured:
        raise ServiceUnavailableError(
            "Video suggestions aren't set up on this server yet.", code="VIDEOS_NOT_CONFIGURED"
        )
    record = await lessons_repo.get_topic(connection, principal.user_id, item_id)
    if record is None:
        raise _topic_not_found()
    topic = record.topic
    # Locking the goal row serialises concurrent requests for its topics (two tabs, a double click).
    goal = await goals_repo.get(connection, principal.user_id, topic.goal_id, for_update=True)
    if goal is None:
        raise _topic_not_found()

    request: dict[str, Any] = {"refresh": True} if payload.refresh else {}
    if idempotency_key:
        existing = await jobs_repo.find_by_idempotency_key(
            connection, principal.user_id, idempotency_key
        )
        if existing is not None:
            stored = await jobs_repo.get_request(connection, principal.user_id, existing.id)
            same = existing.job_type == "resources" and existing.item_id == item_id
            if same and bool((stored or {}).get("refresh")) == payload.refresh:
                return existing  # the same form submitted twice: same job
            raise ConflictError(
                "That Idempotency-Key was already used for a different request.",
                code="IDEMPOTENCY_KEY_REUSED",
            )

    if goal.status == "archived":
        raise ConflictError(
            "This goal is archived. Restore it to find videos for its topics.",
            code="GOAL_ARCHIVED",
        )
    if topic.kind == "revision":
        raise InvalidRequestError(
            "Revision sessions don't have video suggestions: they are a time to recall what you "
            "studied.",
            code="TOPIC_HAS_NO_VIDEOS",
        )
    if record.roadmap.status != "current":
        raise ConflictError(
            "This topic belongs to an earlier roadmap version. Make that version current "
            "before finding videos for it.",
            code="ROADMAP_NOT_CURRENT",
        )
    if (
        not payload.refresh
        and await videos_repo.get_search(connection, principal.user_id, item_id) is not None
    ):
        raise ConflictError("This topic already has video suggestions.", code="VIDEOS_EXIST")
    if (
        await jobs_repo.active_for_item(connection, principal.user_id, item_id, "resources")
        is not None
    ):
        raise ConflictError(
            "Videos are already being found for this topic.", code="VIDEO_SEARCH_ACTIVE"
        )
    allowance = settings.video_searches_per_user_per_day
    since = datetime.now(UTC) - _ALLOWANCE_WINDOW
    if await jobs_repo.count_since(connection, principal.user_id, since, "resources") >= allowance:
        raise RateLimitedError(
            f"You can search for videos up to {allowance} times a day. Please try again tomorrow.",
            code="VIDEO_SEARCH_LIMIT_REACHED",
        )

    try:
        job = await jobs_repo.insert(
            connection,
            principal.user_id,
            topic.goal_id,
            idempotency_key=idempotency_key,
            request=request,
            job_type="resources",
            item_id=item_id,
        )
    except psycopg.errors.UniqueViolation:
        # Lost a race the lock above should already prevent; the database index is the backstop.
        raise ConflictError(
            "Videos are already being found for this topic.", code="VIDEO_SEARCH_ACTIVE"
        ) from None
    # Identifiers only: the topic's words go to YouTube from the worker and stay out of logs.
    log.info("videos.requested", job_id=str(job.id), item_id=str(item_id), refresh=payload.refresh)
    return job


async def retry_job(
    connection: UserConnection, principal: Principal, job: GenerationJob, *, settings: Settings
) -> GenerationJob:
    """Queue a fresh search repeating a failed one. The failed job stays as history."""
    if job.item_id is None:
        raise _topic_not_found()
    has_search = await videos_repo.get_search(connection, principal.user_id, job.item_id)
    return await start_search(
        connection,
        principal,
        job.item_id,
        VideoSearchRequest(refresh=has_search is not None),
        idempotency_key=None,
        settings=settings,
    )
