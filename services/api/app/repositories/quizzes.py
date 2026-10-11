"""SQL for reading a learner's own quizzes, attempts, results and mastery.

Everything here runs as the caller (row security) and filters by ``user_id`` as well. There is no
write here and no answer key: quizzes, questions, attempts, answers and mastery are written by the
worker and the grader, and the key table cannot be read by this role at all. The only way
correctness reaches a response is through ``quiz_answers.feedback``, copied there when the learner
submitted.
"""

from typing import Any
from uuid import UUID

from app.core.db import UserConnection
from app.learning.mastery import MasteryConfig, band_for
from app.schemas.quizzes import (
    AnswerFeedback,
    AnswerResult,
    AttemptBrief,
    AttemptSummary,
    ObjectiveMastery,
    ObjectiveOut,
    OptionOut,
    QuestionOut,
    QuizDetail,
    QuizSummary,
    RubricPointOut,
    TopicMasteryOut,
    YourAnswer,
)

_QUIZ_COLUMNS = """
    z.id, r.goal_id, z.item_id, i.title as item_title, z.lesson_id, z.purpose, z.title,
    z.question_count, z.is_synthetic, z.created_at, z.language, z.focus_objective_ids,
    a.id as attempt_id, a.status as attempt_status, a.submitted_at, a.percent
"""


_QUIZ_JOINS = (
    " join public.roadmaps r on r.id = z.roadmap_id and r.user_id = z.user_id"
    " join public.roadmap_items i on i.id = z.item_id and i.user_id = z.user_id"
    " left join public.quiz_attempts a on a.quiz_id = z.id and a.user_id = z.user_id"
)


def _options(raw: list[dict[str, Any]] | None) -> list[OptionOut] | None:
    return None if raw is None else [OptionOut(id=o["id"], text=o["text"]) for o in raw]


def _summary(row: dict[str, Any]) -> QuizSummary:
    attempt = (
        AttemptBrief(
            id=row["attempt_id"],
            status=row["attempt_status"],
            submitted_at=row["submitted_at"],
            percent=None if row["percent"] is None else float(row["percent"]),
        )
        if row["attempt_id"] is not None
        else None
    )
    return QuizSummary(
        id=row["id"],
        goal_id=row["goal_id"],
        item_id=row["item_id"],
        item_title=row["item_title"],
        lesson_id=row["lesson_id"],
        purpose=row["purpose"],
        title=row["title"],
        question_count=row["question_count"],
        is_synthetic=row["is_synthetic"],
        created_at=row["created_at"],
        status="submitted" if attempt else "ready",
        attempt=attempt,
    )


async def objective_texts(
    connection: UserConnection, user_id: UUID, roadmap_id: UUID
) -> dict[str, str]:
    """The roadmap's objectives by id."""
    cursor = await connection.execute(
        "select objectives from public.roadmaps where id = %s and user_id = %s",
        (roadmap_id, user_id),
    )
    row = await cursor.fetchone()
    return {o["id"]: o["text"] for o in row["objectives"]} if row else {}


async def list_for_item(
    connection: UserConnection, user_id: UUID, item_id: UUID
) -> list[QuizSummary]:
    cursor = await connection.execute(
        f"select {_QUIZ_COLUMNS} from public.quizzes z"  # noqa: S608 - a module constant
        f"{_QUIZ_JOINS}"
        " where z.item_id = %s and z.user_id = %s order by z.created_at desc, z.id desc",
        (item_id, user_id),
    )
    return [_summary(row) for row in await cursor.fetchall()]


async def get_detail(
    connection: UserConnection, user_id: UUID, quiz_id: UUID
) -> tuple[QuizDetail, UUID] | None:
    """A quiz as the learner sees it before answering (and its roadmap's id), or None."""
    cursor = await connection.execute(
        f"select {_QUIZ_COLUMNS}, z.roadmap_id from public.quizzes z"  # noqa: S608
        f"{_QUIZ_JOINS}"
        " where z.id = %s and z.user_id = %s",
        (quiz_id, user_id),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    texts = await objective_texts(connection, user_id, row["roadmap_id"])
    cursor = await connection.execute(
        "select id, position, kind, prompt, options, objective_id, difficulty, max_points"
        " from public.questions where quiz_id = %s and user_id = %s order by position",
        (quiz_id, user_id),
    )
    questions = [
        QuestionOut(
            id=q["id"],
            position=q["position"],
            kind=q["kind"],
            prompt=q["prompt"],
            options=_options(q["options"]),
            objective_id=q["objective_id"],
            objective_text=texts.get(q["objective_id"]),
            difficulty=q["difficulty"],
            max_points=q["max_points"],
        )
        for q in await cursor.fetchall()
    ]
    used = {q.objective_id for q in questions}
    summary = _summary(row)
    return (
        QuizDetail(
            **summary.model_dump(),
            language=row["language"],
            focus_objective_ids=list(row["focus_objective_ids"]),
            objectives=[ObjectiveOut(id=oid, text=texts[oid]) for oid in texts if oid in used],
            questions=questions,
        ),
        row["roadmap_id"],
    )


async def pending_quiz_id(connection: UserConnection, user_id: UUID, item_id: UUID) -> UUID | None:
    """The newest quiz of a topic that has not been taken yet."""
    cursor = await connection.execute(
        "select z.id from public.quizzes z"
        " where z.item_id = %s and z.user_id = %s"
        "   and not exists (select 1 from public.quiz_attempts a where a.quiz_id = z.id)"
        " order by z.created_at desc limit 1",
        (item_id, user_id),
    )
    row = await cursor.fetchone()
    return row["id"] if row else None


async def pending_quiz_ids(
    connection: UserConnection, user_id: UUID, roadmap_id: UUID
) -> dict[UUID, UUID]:
    """item id -> the newest untaken quiz, for every topic of a roadmap."""
    cursor = await connection.execute(
        "select distinct on (z.item_id) z.item_id, z.id from public.quizzes z"
        " where z.roadmap_id = %s and z.user_id = %s"
        "   and not exists (select 1 from public.quiz_attempts a where a.quiz_id = z.id)"
        " order by z.item_id, z.created_at desc",
        (roadmap_id, user_id),
    )
    return {row["item_id"]: row["id"] for row in await cursor.fetchall()}


async def last_attempts(
    connection: UserConnection, user_id: UUID, roadmap_id: UUID
) -> dict[UUID, AttemptBrief]:
    """item id -> the learner's most recent attempt, for every topic of a roadmap."""
    cursor = await connection.execute(
        "select distinct on (z.item_id) z.item_id, a.id, a.status, a.submitted_at, a.percent"
        " from public.quiz_attempts a"
        " join public.quizzes z on z.id = a.quiz_id and z.user_id = a.user_id"
        " where z.roadmap_id = %s and a.user_id = %s"
        " order by z.item_id, a.submitted_at desc",
        (roadmap_id, user_id),
    )
    return {
        row["item_id"]: AttemptBrief(
            id=row["id"],
            status=row["status"],
            submitted_at=row["submitted_at"],
            percent=None if row["percent"] is None else float(row["percent"]),
        )
        for row in await cursor.fetchall()
    }


def _mastery(row: dict[str, Any], texts: dict[str, str], config: MasteryConfig) -> TopicMasteryOut:
    return TopicMasteryOut(
        item_id=row["item_id"],
        score=float(row["score"]),
        # The band and the "early estimate" flag are derived from the stored score and answer count
        # with today's configuration, so changing a threshold applies to every result at once.
        band=band_for(float(row["score"]), config),
        attempts_count=row["attempts_count"],
        answers_count=row["answers_count"],
        low_confidence=row["answers_count"] < config.min_answers,
        objectives=[
            ObjectiveMastery(
                id=o["id"], text=texts.get(o["id"]), score=float(o["score"]), answers=o["answers"]
            )
            for o in row["objectives"]
        ],
        computed_at=row["computed_at"],
        algorithm_version=row["algorithm_version"],
        needs_practice_below=config.needs_practice_below,
        mastered_from=config.mastered_from,
    )


async def mastery_for_roadmap(
    connection: UserConnection,
    user_id: UUID,
    roadmap_id: UUID,
    config: MasteryConfig,
) -> dict[UUID, TopicMasteryOut]:
    texts = await objective_texts(connection, user_id, roadmap_id)
    cursor = await connection.execute(
        "select item_id, score, band, attempts_count, answers_count, low_confidence, objectives,"
        " computed_at, algorithm_version from public.topic_mastery"
        " where roadmap_id = %s and user_id = %s",
        (roadmap_id, user_id),
    )
    return {row["item_id"]: _mastery(row, texts, config) for row in await cursor.fetchall()}


async def attempt_summary(
    connection: UserConnection, user_id: UUID, attempt_id: UUID
) -> tuple[AttemptSummary, dict[str, Any]] | None:
    """An attempt's header (without its answers) plus the quiz row it belongs to, or None."""
    cursor = await connection.execute(
        "select a.id, a.quiz_id, r.goal_id, a.status, a.submitted_at, a.graded_at,"
        " a.points_earned, a.points_possible, a.percent, z.item_id, i.title as item_title,"
        " z.title, z.purpose, z.roadmap_id, z.is_synthetic,"
        " (select count(*) from public.quiz_answers qa where qa.attempt_id = a.id"
        "   and qa.grading_method = 'pending') as pending_answers"
        " from public.quiz_attempts a"
        " join public.quizzes z on z.id = a.quiz_id and z.user_id = a.user_id"
        " join public.roadmaps r on r.id = z.roadmap_id and r.user_id = z.user_id"
        " join public.roadmap_items i on i.id = z.item_id and i.user_id = z.user_id"
        " where a.id = %s and a.user_id = %s",
        (attempt_id, user_id),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    return (
        AttemptSummary(
            id=row["id"],
            quiz_id=row["quiz_id"],
            goal_id=row["goal_id"],
            item_id=row["item_id"],
            item_title=row["item_title"],
            quiz_title=row["title"],
            purpose=row["purpose"],
            status=row["status"],
            submitted_at=row["submitted_at"],
            graded_at=row["graded_at"],
            points_earned=None if row["points_earned"] is None else float(row["points_earned"]),
            points_possible=row["points_possible"],
            percent=None if row["percent"] is None else float(row["percent"]),
            pending_answers=int(row["pending_answers"]),
            grading_job=None,
        ),
        dict(row),
    )


async def attempt_answers(
    connection: UserConnection, user_id: UUID, attempt_id: UUID, texts: dict[str, str]
) -> list[AnswerResult]:
    cursor = await connection.execute(
        "select qa.id, qa.question_id, qa.answer, qa.skipped, qa.grading_method, qa.is_correct,"
        " qa.points_awarded, qa.max_points, qa.feedback, q.position, q.kind, q.prompt, q.options,"
        " q.objective_id, q.difficulty"
        " from public.quiz_answers qa"
        " join public.questions q on q.id = qa.question_id and q.user_id = qa.user_id"
        " where qa.attempt_id = %s and qa.user_id = %s order by q.position",
        (attempt_id, user_id),
    )
    results: list[AnswerResult] = []
    for row in await cursor.fetchall():
        feedback = row["feedback"]
        rubric = feedback.get("rubric")
        results.append(
            AnswerResult(
                id=row["id"],
                question_id=row["question_id"],
                position=row["position"],
                kind=row["kind"],
                prompt=row["prompt"],
                options=_options(row["options"]),
                objective_id=row["objective_id"],
                objective_text=texts.get(row["objective_id"]),
                difficulty=row["difficulty"],
                your_answer=YourAnswer(
                    option_id=row["answer"].get("option_id"), text=row["answer"].get("text")
                ),
                skipped=row["skipped"],
                is_correct=row["is_correct"],
                points_awarded=None
                if row["points_awarded"] is None
                else float(row["points_awarded"]),
                max_points=row["max_points"],
                grading_method=row["grading_method"],
                feedback=AnswerFeedback(
                    explanation=feedback["explanation"],
                    correct_option_id=feedback.get("correct_option_id"),
                    option_notes=feedback.get("option_notes") or {},
                    rubric=None
                    if rubric is None
                    else [
                        RubricPointOut(id=p["id"], text=p["text"], points=p["points"])
                        for p in rubric
                    ],
                    model_answer=feedback.get("model_answer"),
                    matched_point_ids=feedback.get("matched_point_ids") or [],
                    comment=feedback.get("comment"),
                ),
            )
        )
    return results
