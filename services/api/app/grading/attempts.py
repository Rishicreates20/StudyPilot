"""Submitting a quiz: validate the answers, grade what code can grade, store the attempt.

This is the ONE place that reads an answer key while a learner waits (ADR-007, ADR-036), so it is
written to be hard to misuse:

* it runs in a single privileged transaction, and every query filters on the learner's ``user_id``
  and on the quiz it was given: another learner's quiz is simply "not found";
* the learner's submission is checked against the quiz's own questions first (each question at most
  once, only options that exist, the right kind of answer for the kind of question), and anything
  else is refused before a key is looked at;
* multiple-choice and true/false answers are graded by comparing option ids: no model, no guessing;
* the key, the explanation and the rubric are copied into the learner's own answer row at this
  moment, so reading results never touches the key table again, and nothing is revealed before
  this point;
* a quiz can be attempted once (a database unique key), a repeat of the same submission (same
  ``Idempotency-Key``) returns the same attempt, and anything else is a 409.

Short answers are not graded here: they are stored as ``pending`` and a grading job is queued for
the worker. The attempt stays ``grading`` until each of them has a result.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import structlog
from psycopg.types.json import Jsonb

from app.core.db import Database, SystemConnection
from app.core.errors import ConflictError, InvalidRequestError, NotFoundError
from app.grading.finalize import finalize_attempt
from app.learning.mastery import MasteryConfig

log = structlog.get_logger("app.grading")

MAX_ANSWER_CHARS = 2000


@dataclass(frozen=True)
class SubmittedAnswer:
    question_id: UUID
    option_id: str | None = None
    text: str | None = None


@dataclass(frozen=True)
class Submission:
    attempt_id: UUID
    # False when this was a repeat of an earlier identical submission.
    created: bool


def _feedback(question: Mapping[str, Any]) -> dict[str, Any]:
    """What a learner is shown about a question once it is graded."""
    feedback: dict[str, Any] = {
        "explanation": question["explanation"],
        "matched_point_ids": [],
        "comment": None,
    }
    if question["kind"] == "short_answer":
        feedback["rubric"] = question["rubric"]["points"]
        feedback["model_answer"] = question["model_answer"]
    else:
        feedback["correct_option_id"] = question["correct_option_id"]
        feedback["option_notes"] = question["option_notes"]
    return feedback


def _check_answers(
    answers: Sequence[SubmittedAnswer], questions: Mapping[UUID, Mapping[str, Any]]
) -> dict[UUID, SubmittedAnswer]:
    """The answers by question, or a 422 saying what is wrong. Never looks at a key."""
    by_question: dict[UUID, SubmittedAnswer] = {}
    for answer in answers:
        if answer.question_id not in questions:
            raise InvalidRequestError(
                "An answer names a question that is not part of this quiz.",
                code="UNKNOWN_QUESTION",
            )
        if answer.question_id in by_question:
            raise InvalidRequestError(
                "Each question can be answered only once.", code="DUPLICATE_ANSWER"
            )
        question = questions[answer.question_id]
        if question["kind"] == "short_answer":
            if answer.option_id is not None or answer.text is None:
                raise InvalidRequestError(
                    "A short-answer question is answered with text.", code="INVALID_ANSWER"
                )
            if len(answer.text) > MAX_ANSWER_CHARS:
                raise InvalidRequestError(
                    f"A short answer can be at most {MAX_ANSWER_CHARS} characters.",
                    code="ANSWER_TOO_LONG",
                )
        else:
            valid = {option["id"] for option in question["options"]}
            if answer.text is not None or answer.option_id is None:
                raise InvalidRequestError(
                    "A multiple-choice or true/false question is answered with an option.",
                    code="INVALID_ANSWER",
                )
            if answer.option_id not in valid:
                raise InvalidRequestError(
                    "An answer names an option that does not exist for that question.",
                    code="UNKNOWN_OPTION",
                )
        by_question[answer.question_id] = answer
    return by_question


async def submit_attempt(
    database: Database,
    *,
    user_id: UUID,
    quiz_id: UUID,
    answers: Sequence[SubmittedAnswer],
    idempotency_key: str | None,
    config: MasteryConfig,
) -> Submission:
    async with database.system_session() as connection:
        return await _submit(
            connection,
            user_id=user_id,
            quiz_id=quiz_id,
            answers=answers,
            idempotency_key=idempotency_key,
            config=config,
        )


async def _submit(
    connection: SystemConnection,
    *,
    user_id: UUID,
    quiz_id: UUID,
    answers: Sequence[SubmittedAnswer],
    idempotency_key: str | None,
    config: MasteryConfig,
) -> Submission:
    cursor = await connection.execute(
        "select z.id, z.item_id, r.goal_id, g.status as goal_status"
        " from public.quizzes z"
        " join public.roadmaps r on r.id = z.roadmap_id and r.user_id = z.user_id"
        " join public.learning_goals g on g.id = r.goal_id and g.user_id = r.user_id"
        " where z.id = %s and z.user_id = %s for update of z",
        (quiz_id, user_id),
    )
    quiz = await cursor.fetchone()
    if quiz is None:
        raise NotFoundError("Quiz not found.", code="QUIZ_NOT_FOUND")

    cursor = await connection.execute(
        "select id, idempotency_key from public.quiz_attempts where quiz_id = %s and user_id = %s",
        (quiz_id, user_id),
    )
    existing = await cursor.fetchone()
    if existing is not None:
        if idempotency_key is not None and existing["idempotency_key"] == idempotency_key:
            return Submission(attempt_id=existing["id"], created=False)
        raise ConflictError("This quiz has already been submitted.", code="QUIZ_ALREADY_SUBMITTED")
    if quiz["goal_status"] == "archived":
        raise ConflictError(
            "This goal is archived. Restore it to take its quizzes.", code="GOAL_ARCHIVED"
        )

    cursor = await connection.execute(
        "select q.id, q.position, q.kind, q.options, q.objective_id, q.max_points,"
        " k.correct_option_id, k.rubric, k.model_answer, k.explanation, k.option_notes"
        " from public.questions q"
        " join public.question_answer_keys k on k.question_id = q.id and k.user_id = q.user_id"
        " where q.quiz_id = %s and q.user_id = %s order by q.position",
        (quiz_id, user_id),
    )
    rows = await cursor.fetchall()
    questions = {row["id"]: row for row in rows}
    submitted = _check_answers(answers, questions)

    graded: list[dict[str, Any]] = []
    pending = 0
    for row in rows:
        answer = submitted.get(row["id"])
        feedback = _feedback(row)
        entry: dict[str, Any] = {
            "question_id": row["id"],
            "max_points": row["max_points"],
            "feedback": feedback,
            "answer": {},
            "skipped": answer is None,
            "grading_method": "deterministic",
            "is_correct": None,
            "points": 0,
        }
        if row["kind"] == "short_answer":
            text = (answer.text or "").strip() if answer is not None else ""
            if text:
                entry.update(
                    answer={"text": text}, skipped=False, grading_method="pending", points=None
                )
                pending += 1
            else:
                entry.update(answer={}, skipped=True)  # nothing to mark: zero, by code
        else:
            chosen = answer.option_id if answer is not None else None
            correct = chosen is not None and chosen == row["correct_option_id"]
            entry.update(
                answer={"option_id": chosen} if chosen is not None else {},
                skipped=chosen is None,
                is_correct=correct,
                points=row["max_points"] if correct else 0,
            )
        graded.append(entry)

    cursor = await connection.execute(
        "insert into public.quiz_attempts (user_id, quiz_id, status, idempotency_key)"
        " values (%s, %s, 'grading', %s) returning id",
        (user_id, quiz_id, idempotency_key),
    )
    attempt = await cursor.fetchone()
    if attempt is None:
        raise RuntimeError("attempt insert returned no row")
    attempt_id: UUID = attempt["id"]

    for entry in graded:
        await connection.execute(
            "insert into public.quiz_answers (user_id, attempt_id, question_id, answer, skipped,"
            " grading_method, is_correct, points_awarded, max_points, feedback, graded_at)"
            " values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,"
            "         case when %s = 'pending' then null else now() end)",
            (
                user_id,
                attempt_id,
                entry["question_id"],
                Jsonb(entry["answer"]),
                entry["skipped"],
                entry["grading_method"],
                entry["is_correct"],
                entry["points"],
                entry["max_points"],
                Jsonb(entry["feedback"]),
                entry["grading_method"],
            ),
        )

    if pending:
        await connection.execute(
            "insert into public.generation_jobs (user_id, goal_id, attempt_id, job_type)"
            " values (%s, %s, %s, 'grade')",
            (user_id, quiz["goal_id"], attempt_id),
        )
    else:
        await finalize_attempt(connection, user_id=user_id, attempt_id=attempt_id, config=config)
    log.info("quiz.submitted", attempt_id=str(attempt_id), questions=len(graded), pending=pending)
    return Submission(attempt_id=attempt_id, created=True)
