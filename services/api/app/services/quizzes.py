"""Business rules for writing quizzes, taking them, reading results and reviewing marks.

The API never runs the model. Starting a quiz only validates the request and queues a job (in the
caller's own transaction); the worker writes it. Submitting is handed to ``app.grading``, the one
small privileged module that is allowed to read answer keys, and which is given nothing but the
caller's identity and what they submitted. Reading a quiz or a result goes through the caller's own
row security and can never reach an answer key.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import psycopg.errors
import structlog

from app.core.config import Settings
from app.core.db import Database, UserConnection
from app.core.errors import (
    ConflictError,
    InvalidRequestError,
    NotFoundError,
    RateLimitedError,
    ServiceUnavailableError,
)
from app.core.security import Principal
from app.grading.attempts import SubmittedAnswer, submit_attempt
from app.grading.retry import retry_grading
from app.grading.review import review_answer
from app.repositories import goals as goals_repo
from app.repositories import jobs as jobs_repo
from app.repositories import lessons as lessons_repo
from app.repositories import quizzes as quizzes_repo
from app.schemas.jobs import GenerationJob
from app.schemas.quizzes import (
    AssessmentBlock,
    AttemptResult,
    AttemptSubmit,
    QuizDetail,
    QuizList,
    QuizRequest,
    ReviewRequest,
    TopicAssessment,
)
from app.services import progress as progress_service

log = structlog.get_logger("app.quizzes")

_ALLOWANCE_WINDOW = timedelta(hours=24)
# How many of the weakest objectives a practice quiz aims at.
_MAX_FOCUS_OBJECTIVES = 3


def _topic_not_found() -> NotFoundError:
    return NotFoundError("Topic not found.", code="TOPIC_NOT_FOUND")


def _quiz_not_found() -> NotFoundError:
    return NotFoundError("Quiz not found.", code="QUIZ_NOT_FOUND")


def _attempt_not_found() -> NotFoundError:
    return NotFoundError("Attempt not found.", code="ATTEMPT_NOT_FOUND")


async def start_quiz(
    connection: UserConnection,
    principal: Principal,
    item_id: UUID,
    payload: QuizRequest,
    *,
    idempotency_key: str | None,
    settings: Settings,
) -> GenerationJob:
    """Queue a quiz for one topic of the caller's current roadmap, written from its lesson."""
    if not settings.ai_configured:
        raise ServiceUnavailableError(
            "AI quiz generation isn't set up on this server yet.", code="AI_NOT_CONFIGURED"
        )
    record = await lessons_repo.get_topic(connection, principal.user_id, item_id)
    if record is None:
        raise _topic_not_found()
    topic = record.topic
    # Locking the goal row serialises concurrent starts for it (two tabs, a double click).
    goal = await goals_repo.get(connection, principal.user_id, topic.goal_id, for_update=True)
    if goal is None:
        raise _topic_not_found()

    lesson_id = await lessons_repo.get_current_id(connection, principal.user_id, item_id)
    request: dict[str, Any] = {
        "purpose": payload.purpose,
        "question_count": settings.quiz_question_count,
        "max_short_answers": settings.quiz_short_answers,
    }
    if lesson_id is not None:
        request["lesson_id"] = str(lesson_id)
    if payload.purpose == "practice":
        # What to practise is decided here, from the learner's own stored answers: never by
        # the client.
        mastery = await quizzes_repo.mastery_for_roadmap(
            connection,
            principal.user_id,
            topic.roadmap_id,
            progress_service.mastery_config(settings),
        )
        known = mastery.get(item_id)
        if known is not None:
            weak = sorted(
                (o for o in known.objectives if o.score < settings.mastery_needs_practice_below),
                key=lambda o: (o.score, o.id),
            )
            request["focus_objective_ids"] = [o.id for o in weak][:_MAX_FOCUS_OBJECTIVES]

    if idempotency_key:
        existing = await jobs_repo.find_by_idempotency_key(
            connection, principal.user_id, idempotency_key
        )
        if existing is not None:
            stored = await jobs_repo.get_request(connection, principal.user_id, existing.id)
            if (
                existing.job_type == "quiz"
                and existing.item_id == item_id
                and (stored or {}).get("purpose") == payload.purpose
            ):
                return existing  # the same form submitted twice: same job
            raise ConflictError(
                "That Idempotency-Key was already used for a different request.",
                code="IDEMPOTENCY_KEY_REUSED",
            )

    if goal.status == "archived":
        raise ConflictError(
            "This goal is archived. Restore it to take its quizzes.", code="GOAL_ARCHIVED"
        )
    if topic.kind == "revision":
        raise InvalidRequestError(
            "Revision sessions don't have quizzes: they are a time to recall what you studied.",
            code="TOPIC_NOT_LESSONABLE",
        )
    if record.roadmap.status != "current":
        raise ConflictError(
            "This topic belongs to an earlier roadmap version. Make that version current "
            "before writing new quizzes for it.",
            code="ROADMAP_NOT_CURRENT",
        )
    if lesson_id is None:
        raise ConflictError(
            "A quiz is written from the topic's lesson. Write the lesson first.",
            code="LESSON_REQUIRED",
        )
    if await quizzes_repo.pending_quiz_id(connection, principal.user_id, item_id) is not None:
        raise ConflictError(
            "This topic already has a quiz waiting to be taken. Take it first.",
            code="QUIZ_PENDING",
        )
    if await jobs_repo.active_for_item(connection, principal.user_id, item_id, "quiz") is not None:
        raise ConflictError(
            "A quiz is already being written for this topic.", code="QUIZ_JOB_ACTIVE"
        )
    allowance = settings.quiz_jobs_per_user_per_day
    since = datetime.now(UTC) - _ALLOWANCE_WINDOW
    if await jobs_repo.count_since(connection, principal.user_id, since, "quiz") >= allowance:
        raise RateLimitedError(
            f"You can have up to {allowance} quizzes written a day. Please try again tomorrow.",
            code="QUIZ_LIMIT_REACHED",
        )

    try:
        job = await jobs_repo.insert(
            connection,
            principal.user_id,
            topic.goal_id,
            idempotency_key=idempotency_key,
            request=request,
            job_type="quiz",
            item_id=item_id,
        )
    except psycopg.errors.UniqueViolation:
        # Lost a race the lock above should already prevent; the database index is the backstop.
        raise ConflictError(
            "A quiz is already being written for this topic.", code="QUIZ_JOB_ACTIVE"
        ) from None
    # Identifiers only: topic text and answers are user content and stay out of logs.
    log.info("quiz.requested", job_id=str(job.id), item_id=str(item_id), purpose=payload.purpose)
    return job


async def get_assessment(
    connection: UserConnection, principal: Principal, item_id: UUID, *, settings: Settings
) -> TopicAssessment:
    """Where one topic stands on quizzes, and whether a new one can be started."""
    record = await lessons_repo.get_topic(connection, principal.user_id, item_id)
    if record is None or record.topic.kind == "revision":
        raise _topic_not_found()
    user_id = principal.user_id
    roadmap_id = record.topic.roadmap_id
    mastery = await quizzes_repo.mastery_for_roadmap(
        connection, user_id, roadmap_id, progress_service.mastery_config(settings)
    )
    pending = await quizzes_repo.pending_quiz_id(connection, user_id, item_id)
    attempts = await quizzes_repo.last_attempts(connection, user_id, roadmap_id)
    job = await jobs_repo.latest_for_item(connection, user_id, item_id, "quiz")
    has_lesson = await lessons_repo.get_current_id(connection, user_id, item_id) is not None

    blocked_by: AssessmentBlock | None = None
    if record.goal_status == "archived":
        blocked_by = "goal_archived"
    elif record.roadmap.status != "current":
        blocked_by = "roadmap_not_current"
    elif not has_lesson:
        blocked_by = "lesson_required"
    elif pending is not None:
        blocked_by = "quiz_pending"
    elif job is not None and job.status in {"queued", "running"}:
        blocked_by = "quiz_in_progress"

    progress = await progress_service.roadmap_progress(
        connection,
        principal,
        goal_id=record.topic.goal_id,
        roadmap_id=roadmap_id,
        settings=settings,
    )
    return TopicAssessment(
        item_id=item_id,
        mastery=mastery.get(item_id),
        pending_quiz_id=pending,
        last_attempt=attempts.get(item_id),
        job=job,
        can_start=blocked_by is None,
        blocked_by=blocked_by,
        recommendation=progress.recommendation,
    )


async def retry_quiz_job(
    connection: UserConnection, principal: Principal, job: GenerationJob, *, settings: Settings
) -> GenerationJob:
    """Queue a fresh quiz job repeating a failed one. The failed job stays as history."""
    if job.item_id is None:
        raise _topic_not_found()
    request = await jobs_repo.get_request(connection, principal.user_id, job.id) or {}
    purpose = "practice" if request.get("purpose") == "practice" else "check"
    return await start_quiz(
        connection,
        principal,
        job.item_id,
        QuizRequest(purpose=purpose),
        idempotency_key=None,
        settings=settings,
    )


async def list_quizzes(connection: UserConnection, principal: Principal, item_id: UUID) -> QuizList:
    record = await lessons_repo.get_topic(connection, principal.user_id, item_id)
    if record is None or record.topic.kind == "revision":
        raise _topic_not_found()
    return QuizList(items=await quizzes_repo.list_for_item(connection, principal.user_id, item_id))


async def get_quiz(connection: UserConnection, principal: Principal, quiz_id: UUID) -> QuizDetail:
    found = await quizzes_repo.get_detail(connection, principal.user_id, quiz_id)
    if found is None:
        raise _quiz_not_found()
    return found[0]


async def submit(
    database: Database,
    connection: UserConnection,
    principal: Principal,
    quiz_id: UUID,
    payload: AttemptSubmit,
    *,
    idempotency_key: str | None,
    settings: Settings,
) -> tuple[AttemptResult, bool]:
    """Submit and grade a quiz. Returns the result and whether this call created the attempt."""
    if await quizzes_repo.get_detail(connection, principal.user_id, quiz_id) is None:
        raise _quiz_not_found()
    submission = await submit_attempt(
        database,
        user_id=principal.user_id,
        quiz_id=quiz_id,
        answers=[
            SubmittedAnswer(question_id=a.question_id, option_id=a.option_id, text=a.text)
            for a in payload.answers
        ],
        idempotency_key=idempotency_key,
        config=progress_service.mastery_config(settings),
    )
    return (
        await _result(connection, principal, submission.attempt_id, settings=settings),
        submission.created,
    )


async def get_attempt(
    connection: UserConnection, principal: Principal, attempt_id: UUID, *, settings: Settings
) -> AttemptResult:
    return await _result(connection, principal, attempt_id, settings=settings)


async def _result(
    connection: UserConnection, principal: Principal, attempt_id: UUID, *, settings: Settings
) -> AttemptResult:
    """An attempt with its graded answers, the topic's mastery and the recommended next step."""
    found = await quizzes_repo.attempt_summary(connection, principal.user_id, attempt_id)
    if found is None:
        raise _attempt_not_found()
    summary, row = found
    texts = await quizzes_repo.objective_texts(connection, principal.user_id, row["roadmap_id"])
    answers = await quizzes_repo.attempt_answers(connection, principal.user_id, attempt_id, texts)
    job = await jobs_repo.latest_for_attempt(connection, principal.user_id, attempt_id)
    mastery = await quizzes_repo.mastery_for_roadmap(
        connection, principal.user_id, row["roadmap_id"], progress_service.mastery_config(settings)
    )
    goal_id = await _goal_of(connection, principal, summary.item_id)
    recommendation = None
    if goal_id is not None:
        progress = await progress_service.roadmap_progress(
            connection,
            principal,
            goal_id=goal_id,
            roadmap_id=row["roadmap_id"],
            settings=settings,
        )
        recommendation = progress.recommendation
    return AttemptResult(
        **summary.model_dump(exclude={"grading_job"}),
        grading_job=job,
        is_synthetic=row["is_synthetic"],
        answers=answers,
        mastery=mastery.get(summary.item_id),
        recommendation=recommendation,
    )


async def _goal_of(connection: UserConnection, principal: Principal, item_id: UUID) -> UUID | None:
    record = await lessons_repo.get_topic(connection, principal.user_id, item_id)
    return record.topic.goal_id if record else None


async def review(
    database: Database,
    connection: UserConnection,
    principal: Principal,
    answer_id: UUID,
    payload: ReviewRequest,
    *,
    settings: Settings,
) -> AttemptResult:
    """Record the learner's own review of a short answer and return the updated result."""
    attempt_id = await review_answer(
        database,
        user_id=principal.user_id,
        answer_id=answer_id,
        met_point_ids=payload.met_point_ids,
        config=progress_service.mastery_config(settings),
    )
    return await _result(connection, principal, attempt_id, settings=settings)


async def regrade(
    database: Database, connection: UserConnection, principal: Principal, attempt_id: UUID
) -> GenerationJob:
    """Ask for the attempt's short answers to be marked again."""
    job_id = await retry_grading(database, user_id=principal.user_id, attempt_id=attempt_id)
    job = await jobs_repo.get(connection, principal.user_id, job_id)
    if job is None:
        raise _attempt_not_found()
    return job
