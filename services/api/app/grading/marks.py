"""Reading the short answers that await marking, and applying a model's marks to them.

Used by the grading worker (``app/jobs/grade_job.py``). Everything here runs on the worker's
privileged connection and filters by the job's ``user_id`` and ``attempt_id``. The rubric comes from
the copy stored in the learner's own answer row at submission time, so the answer-key table is
not read again. A mark only ever lands on an answer that is still ``pending``: a learner's own
review, or a result that has already been applied, is never overwritten.
"""

from collections.abc import Sequence
from uuid import UUID

from psycopg.types.json import Jsonb

from app.ai.grading.grader import AnswerToGrade, MarkedAnswer, RubricPointInput
from app.core.db import SystemConnection
from app.grading.finalize import finalize_attempt
from app.jobs import queue
from app.jobs.errors import JobCancelled, LeaseLost
from app.jobs.queue import Job
from app.learning.mastery import MasteryConfig


async def load_pending(
    connection: SystemConnection, *, user_id: UUID, attempt_id: UUID
) -> tuple[str, tuple[AnswerToGrade, ...]]:
    """The quiz's language and every short answer of the attempt that still needs a mark."""
    cursor = await connection.execute(
        "select qa.id, qa.answer, qa.feedback, q.prompt, z.language"
        " from public.quiz_answers qa"
        " join public.questions q on q.id = qa.question_id and q.user_id = qa.user_id"
        " join public.quizzes z on z.id = q.quiz_id and z.user_id = q.user_id"
        " where qa.attempt_id = %s and qa.user_id = %s and qa.grading_method = 'pending'"
        " order by q.position",
        (attempt_id, user_id),
    )
    rows = await cursor.fetchall()
    language = rows[0]["language"] if rows else "en"
    return language, tuple(
        AnswerToGrade(
            answer_id=str(row["id"]),
            question=row["prompt"],
            rubric=tuple(
                RubricPointInput(point["id"], point["text"], point["points"])
                for point in row["feedback"]["rubric"]
            ),
            model_answer=row["feedback"]["model_answer"],
            learner_answer=row["answer"]["text"],
        )
        for row in rows
    )


async def apply_marks(
    connection: SystemConnection,
    job: Job,
    worker_id: str,
    marks: Sequence[MarkedAnswer],
    *,
    config: MasteryConfig,
) -> None:
    """Store the marks, close the attempt if that was the last of them, and finish the job."""
    if job.attempt_id is None:
        raise LeaseLost
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

    for mark in marks:
        cursor = await connection.execute(
            "select id, max_points, feedback from public.quiz_answers"
            " where id = %s and attempt_id = %s and user_id = %s and grading_method = 'pending'"
            " for update",
            (UUID(mark.answer_id), job.attempt_id, job.user_id),
        )
        answer = await cursor.fetchone()
        if answer is None:
            continue  # already marked (or reviewed by the learner): leave it alone
        rubric: dict[str, int] = {p["id"]: p["points"] for p in answer["feedback"]["rubric"]}
        met = [point for point in mark.met_point_ids if point in rubric]
        points = round(answer["max_points"] * sum(rubric[p] for p in met) / sum(rubric.values()), 2)
        feedback = {**answer["feedback"], "matched_point_ids": met, "comment": mark.comment}
        await connection.execute(
            "update public.quiz_answers set grading_method = 'ai_estimate', points_awarded = %s,"
            " feedback = %s, graded_at = now() where id = %s and user_id = %s",
            (points, Jsonb(feedback), answer["id"], job.user_id),
        )
    await finalize_attempt(
        connection, user_id=job.user_id, attempt_id=job.attempt_id, config=config
    )
    if not await queue.complete(connection, job.id, worker_id):
        raise LeaseLost  # rolls the whole transaction back
