from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Header, Request, Response

from app.api.deps import DatabaseDep
from app.core.errors import ProblemDetail
from app.core.security import CurrentPrincipal
from app.schemas.jobs import GenerationJob
from app.schemas.quizzes import (
    AttemptResult,
    AttemptSubmit,
    GoalProgress,
    QuizDetail,
    QuizList,
    QuizRequest,
    ReviewRequest,
    TopicAssessment,
)
from app.services import progress as progress_service
from app.services import quizzes as quizzes_service

router = APIRouter(tags=["quizzes"])

_NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {
        "model": ProblemDetail,
        "description": "No such topic, quiz, attempt or goal for this user",
    }
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
        description="Send the same value when resubmitting a form: you get the same result back.",
    ),
]


@router.post(
    "/roadmap-items/{item_id}/quizzes",
    response_model=GenerationJob,
    status_code=202,
    summary="Start writing a quiz for a roadmap topic",
    responses={
        **_NOT_FOUND,
        **_CONFLICT,
        422: {"model": ProblemDetail, "description": "Revision sessions don't have quizzes"},
        429: {"model": ProblemDetail, "description": "Today's quiz allowance is used up"},
        503: {"model": ProblemDetail, "description": "AI generation isn't configured"},
    },
)
async def start_quiz(
    item_id: UUID,
    payload: QuizRequest,
    request: Request,
    response: Response,
    principal: CurrentPrincipal,
    database: DatabaseDep,
    idempotency_key: IdempotencyKey = None,
) -> GenerationJob:
    """Queues a background job and returns it at once (202); poll `GET /v1/jobs/{id}`.

    The quiz is written from the topic's current lesson (409 `LESSON_REQUIRED` without one) and
    has no answers in it that a browser can read. At most one untaken quiz exists per topic.
    """
    settings = request.app.state.settings
    async with database.user_transaction(principal) as connection:
        job = await quizzes_service.start_quiz(
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
    "/roadmap-items/{item_id}/quizzes",
    response_model=QuizList,
    summary="The quizzes written for a topic, newest first",
    responses=_NOT_FOUND,
)
async def list_quizzes(
    item_id: UUID, principal: CurrentPrincipal, database: DatabaseDep
) -> QuizList:
    async with database.user_transaction(principal) as connection:
        return await quizzes_service.list_quizzes(connection, principal, item_id)


@router.get(
    "/roadmap-items/{item_id}/assessment",
    response_model=TopicAssessment,
    summary="Where a topic stands on quizzes and mastery, and whether a quiz can be started",
    responses=_NOT_FOUND,
)
async def read_assessment(
    item_id: UUID, request: Request, principal: CurrentPrincipal, database: DatabaseDep
) -> TopicAssessment:
    async with database.user_transaction(principal) as connection:
        return await quizzes_service.get_assessment(
            connection, principal, item_id, settings=request.app.state.settings
        )


@router.get(
    "/quizzes/{quiz_id}",
    response_model=QuizDetail,
    summary="A quiz to take: questions and options only",
    responses=_NOT_FOUND,
)
async def read_quiz(
    quiz_id: UUID, principal: CurrentPrincipal, database: DatabaseDep
) -> QuizDetail:
    """Never contains a correct answer, an explanation or a rubric, before or after submission."""
    async with database.user_transaction(principal) as connection:
        return await quizzes_service.get_quiz(connection, principal, quiz_id)


@router.post(
    "/quizzes/{quiz_id}/attempts",
    response_model=AttemptResult,
    status_code=201,
    summary="Submit answers and get them graded",
    responses={
        **_NOT_FOUND,
        **_CONFLICT,
        200: {"model": AttemptResult, "description": "The same submission again: the same result"},
        422: {
            "model": ProblemDetail,
            "description": "An answer names an unknown question or option",
        },
    },
)
async def submit_attempt(
    quiz_id: UUID,
    payload: AttemptSubmit,
    request: Request,
    response: Response,
    principal: CurrentPrincipal,
    database: DatabaseDep,
    idempotency_key: IdempotencyKey = None,
) -> AttemptResult:
    """Multiple-choice and true/false answers are graded here, by comparing option ids; short
    answers are marked in the background against their rubric (an estimate). A quiz can be
    submitted once. Correct answers and explanations are revealed in this response, not before."""
    settings = request.app.state.settings
    async with database.user_transaction(principal) as connection:
        result, created = await quizzes_service.submit(
            database,
            connection,
            principal,
            quiz_id,
            payload,
            idempotency_key=idempotency_key,
            settings=settings,
        )
    if not created:
        response.status_code = 200
    return result


@router.get(
    "/quiz-attempts/{attempt_id}",
    response_model=AttemptResult,
    summary="The results of a submitted quiz",
    responses=_NOT_FOUND,
)
async def read_attempt(
    attempt_id: UUID, request: Request, principal: CurrentPrincipal, database: DatabaseDep
) -> AttemptResult:
    async with database.user_transaction(principal) as connection:
        return await quizzes_service.get_attempt(
            connection, principal, attempt_id, settings=request.app.state.settings
        )


@router.post(
    "/quiz-attempts/{attempt_id}/regrade",
    response_model=GenerationJob,
    status_code=202,
    summary="Ask for the short answers to be marked again",
    responses={**_NOT_FOUND, **_CONFLICT},
)
async def regrade_attempt(
    attempt_id: UUID,
    response: Response,
    principal: CurrentPrincipal,
    database: DatabaseDep,
) -> GenerationJob:
    async with database.user_transaction(principal) as connection:
        job = await quizzes_service.regrade(database, connection, principal, attempt_id)
    response.headers["Location"] = f"/v1/jobs/{job.id}"
    return job


@router.put(
    "/quiz-answers/{answer_id}/review",
    response_model=AttemptResult,
    summary="Review the marking of one of your short answers",
    responses={**_NOT_FOUND, **_CONFLICT, 422: {"model": ProblemDetail}},
)
async def review_answer(
    answer_id: UUID,
    payload: ReviewRequest,
    request: Request,
    principal: CurrentPrincipal,
    database: DatabaseDep,
) -> AttemptResult:
    """Say which rubric points your answer covered. The server computes the points from the rubric
    and your review replaces the estimate."""
    async with database.user_transaction(principal) as connection:
        return await quizzes_service.review(
            database,
            connection,
            principal,
            answer_id,
            payload,
            settings=request.app.state.settings,
        )


@router.get(
    "/goals/{goal_id}/progress",
    response_model=GoalProgress,
    summary="Topic-by-topic mastery of a goal's roadmap and the recommended next step",
    responses=_NOT_FOUND,
)
async def goal_progress(
    goal_id: UUID, request: Request, principal: CurrentPrincipal, database: DatabaseDep
) -> GoalProgress:
    async with database.user_transaction(principal) as connection:
        return await progress_service.goal_progress(
            connection, principal, goal_id, settings=request.app.state.settings
        )
