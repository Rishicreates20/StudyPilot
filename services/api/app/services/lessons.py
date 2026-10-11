"""Business rules for writing lessons, studying them, and recording progress.

The API never runs the model. Starting a lesson only validates the request and queues a job (in the
caller's own transaction); the worker does the rest. Every rule here that protects money or data
(one lesson at a time per topic, a cap on lessons in flight, a daily allowance, archived goals are
read-only) is also backed by the database where it can be.
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
from app.schemas.jobs import GenerationJob
from app.schemas.lessons import (
    LessonRequest,
    NeighbourTopic,
    ProgressState,
    ProgressUpdate,
    StudyView,
)

log = structlog.get_logger("app.lessons")

_ALLOWANCE_WINDOW = timedelta(hours=24)
# The parts of a lesson request that make two requests "the same" for idempotency.
_IDENTITY_KEYS = ("adjust", "feedback", "regenerate")


def _topic_not_found() -> NotFoundError:
    # Same answer for "does not exist", "belongs to someone else" and "is not a lesson topic".
    return NotFoundError("Topic not found.", code="TOPIC_NOT_FOUND")


def _lesson_not_found() -> NotFoundError:
    return NotFoundError("Lesson not found.", code="LESSON_NOT_FOUND")


def _archived() -> ConflictError:
    return ConflictError(
        "This goal is archived. Restore it to work with its lessons.", code="GOAL_ARCHIVED"
    )


def _identity(request: dict[str, Any]) -> dict[str, Any]:
    return {key: request.get(key) for key in _IDENTITY_KEYS if request.get(key)}


async def start_generation(
    connection: UserConnection,
    principal: Principal,
    item_id: UUID,
    payload: LessonRequest,
    *,
    idempotency_key: str | None,
    settings: Settings,
) -> GenerationJob:
    """Queue a lesson for one topic of the caller's current roadmap, or a new version of it."""
    if not settings.ai_configured:
        raise ServiceUnavailableError(
            "AI lesson generation isn't set up on this server yet.", code="AI_NOT_CONFIGURED"
        )
    record = await lessons_repo.get_topic(connection, principal.user_id, item_id)
    if record is None:
        raise _topic_not_found()
    topic = record.topic
    # Locking the goal row serialises concurrent starts for its topics (two tabs, a double click).
    goal = await goals_repo.get(connection, principal.user_id, topic.goal_id, for_update=True)
    if goal is None:
        raise _topic_not_found()

    regenerate = payload.regenerate or payload.adjust is not None or payload.feedback is not None
    request: dict[str, Any] = {}
    if payload.adjust:
        request["adjust"] = payload.adjust
    if payload.feedback:
        request["feedback"] = payload.feedback
    current_id = await lessons_repo.get_current_id(connection, principal.user_id, item_id)
    if regenerate:
        request["regenerate"] = True
        if current_id is not None:
            request["base_lesson_id"] = str(current_id)

    if idempotency_key:
        existing = await jobs_repo.find_by_idempotency_key(
            connection, principal.user_id, idempotency_key
        )
        if existing is not None:
            stored = await jobs_repo.get_request(connection, principal.user_id, existing.id)
            if existing.item_id == item_id and _identity(stored or {}) == _identity(request):
                return existing  # the same form submitted twice: same job
            raise ConflictError(
                "That Idempotency-Key was already used for a different request.",
                code="IDEMPOTENCY_KEY_REUSED",
            )

    if goal.status == "archived":
        raise _archived()
    if topic.kind == "revision":
        raise InvalidRequestError(
            "Revision sessions don't have lessons: they are a time to recall what you studied.",
            code="TOPIC_NOT_LESSONABLE",
        )
    if record.roadmap.status != "current":
        raise ConflictError(
            "This topic belongs to an earlier roadmap version. Make that version current "
            "before writing new lessons for it.",
            code="ROADMAP_NOT_CURRENT",
        )
    if current_id is not None and not regenerate:
        raise ConflictError("This topic already has a lesson.", code="LESSON_EXISTS")
    if await jobs_repo.active_for_item(connection, principal.user_id, item_id) is not None:
        raise ConflictError(
            "A lesson is already being written for this topic.", code="LESSON_JOB_ACTIVE"
        )
    in_flight = settings.lesson_jobs_active_per_user
    if await jobs_repo.count_active_lessons(connection, principal.user_id) >= in_flight:
        raise RateLimitedError(
            f"{in_flight} lessons are already being written for you. "
            "Please wait for one to finish.",
            code="LESSON_QUEUE_FULL",
        )
    allowance = settings.lesson_jobs_per_user_per_day
    since = datetime.now(UTC) - _ALLOWANCE_WINDOW
    if await jobs_repo.count_since(connection, principal.user_id, since, "lesson") >= allowance:
        raise RateLimitedError(
            f"You can have up to {allowance} lessons written a day. Please try again tomorrow.",
            code="LESSON_LIMIT_REACHED",
        )

    try:
        job = await jobs_repo.insert(
            connection,
            principal.user_id,
            topic.goal_id,
            idempotency_key=idempotency_key,
            request=request,
            job_type="lesson",
            item_id=item_id,
        )
    except psycopg.errors.UniqueViolation:
        # Lost a race the lock above should already prevent; the database index is the backstop.
        raise ConflictError(
            "A lesson is already being written for this topic.", code="LESSON_JOB_ACTIVE"
        ) from None
    # Identifiers only: topic text and feedback are user content and stay out of logs.
    log.info(
        "lesson.requested",
        job_id=str(job.id),
        item_id=str(item_id),
        regenerate=regenerate,
        adjust=payload.adjust,
    )
    return job


async def retry_job(
    connection: UserConnection, principal: Principal, job: GenerationJob, *, settings: Settings
) -> GenerationJob:
    """Queue a fresh lesson job repeating a failed one. The failed job stays as history."""
    request = await jobs_repo.get_request(connection, principal.user_id, job.id) or {}
    adjust = request.get("adjust")
    feedback = request.get("feedback")
    if job.item_id is None:
        raise _topic_not_found()
    return await start_generation(
        connection,
        principal,
        job.item_id,
        LessonRequest.model_validate(
            {
                "adjust": adjust if isinstance(adjust, str) else None,
                "feedback": feedback if isinstance(feedback, str) else None,
                "regenerate": bool(request.get("regenerate")),
            }
        ),
        idempotency_key=None,
        settings=settings,
    )


async def get_study(
    connection: UserConnection,
    principal: Principal,
    item_id: UUID,
    *,
    lesson_id: UUID | None = None,
) -> StudyView:
    """The study page's data for one topic: its lesson, progress, job and neighbours."""
    record = await lessons_repo.get_topic(connection, principal.user_id, item_id)
    if record is None or record.topic.kind == "revision":
        raise _topic_not_found()
    lesson = await lessons_repo.get_detail(connection, principal.user_id, item_id, lesson_id)
    if lesson is None and lesson_id is not None:
        raise _lesson_not_found()

    versions = await lessons_repo.list_versions(connection, principal.user_id, item_id)
    progress = (
        await lessons_repo.get_progress(connection, principal.user_id, lesson.id)
        if lesson is not None
        else None
    )
    job = await jobs_repo.latest_for_item(connection, principal.user_id, item_id)
    outline = await lessons_repo.outline(connection, principal.user_id, record.topic.roadmap_id)

    position = next((i for i, entry in enumerate(outline) if entry.item_id == item_id), None)
    previous = (
        NeighbourTopic(id=outline[position - 1].item_id, title=outline[position - 1].title)
        if position is not None and position > 0
        else None
    )
    following = (
        NeighbourTopic(id=outline[position + 1].item_id, title=outline[position + 1].title)
        if position is not None and position + 1 < len(outline)
        else None
    )
    archived = record.goal_status == "archived"
    return StudyView(
        topic=record.topic,
        roadmap=record.roadmap,
        lesson=lesson,
        versions=versions,
        progress=progress,
        job=job,
        previous=previous,
        next=following,
        outline=outline,
        goal_archived=archived,
        can_generate=record.roadmap.status == "current" and not archived,
    )


async def save_progress(
    connection: UserConnection, principal: Principal, lesson_id: UUID, payload: ProgressUpdate
) -> ProgressState:
    """Record the learner's place in a lesson. Replaces what was saved before."""
    ref = await lessons_repo.get_ref(connection, principal.user_id, lesson_id)
    if ref is None:
        raise _lesson_not_found()
    if ref.goal_status == "archived":
        raise _archived()

    known = set(ref.section_ids)
    done = set(payload.completed_section_ids)
    if len(done) != len(payload.completed_section_ids) or not done <= known:
        raise InvalidRequestError(
            "Progress can only name each of this lesson's own sections once.",
            code="UNKNOWN_SECTION",
        )
    if payload.current_section_id is not None and payload.current_section_id not in known:
        raise InvalidRequestError(
            "That section is not part of this lesson.", code="UNKNOWN_SECTION"
        )
    if payload.completed:
        done = known
    state = await lessons_repo.save_progress(
        connection,
        principal.user_id,
        lesson_id,
        # In the lesson's own order, whatever order the browser sent.
        completed_section_ids=[s for s in ref.section_ids if s in done],
        current_section_id=payload.current_section_id,
        completed=payload.completed,
    )
    log.info(
        "lesson.progress_saved",
        lesson_id=str(lesson_id),
        status=state.status,
        sections_done=len(state.completed_section_ids),
    )
    return state
