"""Reading what a quiz is written from, and writing a finished quiz, for the worker (privileged).

``save_quiz`` is the only place a quiz is created. It runs in ONE transaction that

1. confirms this worker still owns the job (and the learner has not cancelled it),
2. locks the goal, which refuses archived or deleted goals,
3. returns the existing quiz if this job already stored one (a retry after a crash),
4. stores the quiz and its questions (what a learner may see) and, separately, the answer keys
   (the right answers, explanations and rubrics, which no browser-facing role can read),
5. marks the job completed,

so a quiz is either fully stored and the job finished, or nothing changed at all.
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from app.ai.quiz.context import Purpose, QuizObjective
from app.ai.quiz.schema import (
    BuiltMultipleChoice,
    BuiltQuiz,
    BuiltShortAnswer,
)
from app.core.db import SystemConnection
from app.jobs import queue
from app.jobs.errors import JobCancelled, JobFailure, LeaseLost
from app.jobs.queue import Job

_MAX_PREVIOUS_PROMPTS = 40


@dataclass(frozen=True)
class QuizMeta:
    """How and with what a quiz was produced; stored with it."""

    prompt_version: str
    provider: str
    model_id: str
    synthetic: bool


@dataclass(frozen=True)
class SavedQuiz:
    id: UUID


async def load_objectives(
    connection: SystemConnection, user_id: UUID, item_id: UUID
) -> tuple[QuizObjective, ...]:
    """The roadmap objectives a topic serves (all of the roadmap's if it names none)."""
    cursor = await connection.execute(
        "select i.objective_ids, r.objectives from public.roadmap_items i"
        " join public.roadmaps r on r.id = i.roadmap_id and r.user_id = i.user_id"
        " where i.id = %s and i.user_id = %s",
        (item_id, user_id),
    )
    row = await cursor.fetchone()
    if row is None:
        return ()
    text = {objective["id"]: objective["text"] for objective in row["objectives"]}
    chosen = [QuizObjective(oid, text[oid]) for oid in row["objective_ids"] if oid in text]
    return tuple(chosen or (QuizObjective(oid, body) for oid, body in text.items()))


async def load_previous_prompts(
    connection: SystemConnection, user_id: UUID, item_id: UUID
) -> tuple[str, ...]:
    """The questions already asked about this topic (never their answers), newest first."""
    cursor = await connection.execute(
        "select q.prompt from public.questions q"
        " join public.quizzes z on z.id = q.quiz_id and z.user_id = q.user_id"
        " where z.item_id = %s and z.user_id = %s order by z.created_at desc, q.position"
        " limit %s",
        (item_id, user_id, _MAX_PREVIOUS_PROMPTS),
    )
    return tuple(row["prompt"] for row in await cursor.fetchall())


async def save_quiz(
    connection: SystemConnection,
    job: Job,
    worker_id: str,
    *,
    roadmap_id: UUID,
    item_id: UUID,
    lesson_id: UUID,
    quiz: BuiltQuiz,
    meta: QuizMeta,
    purpose: Purpose,
    focus_objective_ids: list[str],
) -> SavedQuiz:
    """Store ``quiz`` and its answer keys and finish the job. Call inside one session."""
    cursor = await connection.execute(
        "select cancel_requested from public.generation_jobs"
        " where id = %s and locked_by = %s and status = 'running' for update",
        (job.id, worker_id),
    )
    owned = await cursor.fetchone()
    if owned is None:
        raise LeaseLost
    if owned["cancel_requested"]:
        raise JobCancelled

    cursor = await connection.execute(
        "select status from public.learning_goals where id = %s and user_id = %s for update",
        (job.goal_id, job.user_id),
    )
    goal = await cursor.fetchone()
    if goal is None or goal["status"] == "archived":
        raise JobFailure(
            "GOAL_UNAVAILABLE", "This goal was archived or deleted before the quiz was ready."
        )

    cursor = await connection.execute("select id from public.quizzes where job_id = %s", (job.id,))
    existing = await cursor.fetchone()
    if existing is not None:  # a retry after a crash between "stored" and "marked complete"
        await queue.complete(connection, job.id, worker_id)
        return SavedQuiz(id=existing["id"])

    cursor = await connection.execute(
        "insert into public.quizzes (user_id, roadmap_id, item_id, lesson_id, job_id, purpose,"
        " focus_objective_ids, title, language, question_count, prompt_version, provider, model_id,"
        " is_synthetic) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
        " returning id",
        (
            job.user_id,
            roadmap_id,
            item_id,
            lesson_id,
            job.id,
            purpose,
            focus_objective_ids,
            quiz.title,
            quiz.language,
            len(quiz.questions),
            meta.prompt_version,
            meta.provider,
            meta.model_id,
            meta.synthetic,
        ),
    )
    row = await cursor.fetchone()
    if row is None:
        raise RuntimeError("quiz insert returned no row")
    quiz_id: UUID = row["id"]

    for position, question in enumerate(quiz.questions, start=1):
        options = (
            None
            if isinstance(question, BuiltShortAnswer)
            else Jsonb([option.model_dump() for option in question.options])
        )
        cursor = await connection.execute(
            "insert into public.questions (user_id, quiz_id, position, kind, prompt, options,"
            " objective_id, difficulty, max_points) values (%s, %s, %s, %s, %s, %s, %s, %s, %s)"
            " returning id",
            (
                job.user_id,
                quiz_id,
                position,
                question.kind,
                question.prompt,
                options,
                question.objective_id,
                question.difficulty,
                question.max_points,
            ),
        )
        question_row = await cursor.fetchone()
        if question_row is None:
            raise RuntimeError("question insert returned no row")
        correct: str | None = None
        rubric: Jsonb | None = None
        model_answer: str | None = None
        notes: dict[str, str] = {}
        if isinstance(question, BuiltShortAnswer):
            rubric = Jsonb({"points": [point.model_dump() for point in question.rubric]})
            model_answer = question.model_answer
        else:
            correct = question.correct_option_id
            if isinstance(question, BuiltMultipleChoice):
                notes = question.option_notes
        await connection.execute(
            "insert into public.question_answer_keys (question_id, user_id, correct_option_id,"
            " rubric, model_answer, explanation, option_notes) values (%s, %s, %s, %s, %s, %s, %s)",
            (
                question_row["id"],
                job.user_id,
                correct,
                rubric,
                model_answer,
                question.explanation,
                Jsonb(notes),
            ),
        )
    if not await queue.complete(connection, job.id, worker_id):
        raise LeaseLost  # rolls the whole transaction back
    return SavedQuiz(id=quiz_id)


def checkpoint_of(quiz: BuiltQuiz, meta: QuizMeta) -> dict[str, Any]:
    """What a retry needs to skip the (paid) writing step."""
    return {
        "quiz": quiz.model_dump(mode="json"),
        "meta": {
            "prompt_version": meta.prompt_version,
            "provider": meta.provider,
            "model_id": meta.model_id,
            "synthetic": meta.synthetic,
        },
    }


def restore_checkpoint(checkpoint: dict[str, Any]) -> tuple[BuiltQuiz, QuizMeta]:
    return BuiltQuiz.model_validate(checkpoint["quiz"]), QuizMeta(**checkpoint["meta"])
