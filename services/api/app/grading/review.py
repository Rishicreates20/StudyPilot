"""A learner reviewing the result of one of their short answers.

A model's marking of free text is an estimate (ADR-037), so the learner always has the last
word: after seeing the rubric and the model answer they can say which rubric points their answer
really covered. Their review replaces the estimate (``self_review``), the points are recomputed
here from the rubric (a client never sends points), and the attempt's totals and the topic's
mastery follow.
"""

from collections.abc import Sequence
from uuid import UUID

import structlog
from psycopg.types.json import Jsonb

from app.core.db import Database
from app.core.errors import ConflictError, InvalidRequestError, NotFoundError
from app.grading.finalize import finalize_attempt
from app.learning.mastery import MasteryConfig

log = structlog.get_logger("app.grading")


async def review_answer(
    database: Database,
    *,
    user_id: UUID,
    answer_id: UUID,
    met_point_ids: Sequence[str],
    config: MasteryConfig,
) -> UUID:
    """Record which rubric points the learner's own answer covered. Returns the attempt's id."""
    async with database.system_session() as connection:
        cursor = await connection.execute(
            "select qa.id, qa.attempt_id, qa.skipped, qa.max_points, qa.feedback, q.kind,"
            " g.status as goal_status"
            " from public.quiz_answers qa"
            " join public.questions q on q.id = qa.question_id and q.user_id = qa.user_id"
            " join public.quizzes z on z.id = q.quiz_id and z.user_id = q.user_id"
            " join public.roadmaps r on r.id = z.roadmap_id and r.user_id = z.user_id"
            " join public.learning_goals g on g.id = r.goal_id and g.user_id = r.user_id"
            " where qa.id = %s and qa.user_id = %s for update of qa",
            (answer_id, user_id),
        )
        answer = await cursor.fetchone()
        if answer is None:
            raise NotFoundError("Answer not found.", code="ANSWER_NOT_FOUND")
        if answer["kind"] != "short_answer" or answer["skipped"]:
            raise ConflictError(
                "Only an answer you wrote in your own words can be reviewed.",
                code="NOT_REVIEWABLE",
            )
        if answer["goal_status"] == "archived":
            raise ConflictError(
                "This goal is archived. Restore it to review its quizzes.", code="GOAL_ARCHIVED"
            )

        rubric: dict[str, int] = {
            point["id"]: point["points"] for point in answer["feedback"]["rubric"]
        }
        chosen = list(dict.fromkeys(met_point_ids))
        if any(point not in rubric for point in chosen):
            raise InvalidRequestError(
                "A review can only name points of this question's rubric.",
                code="UNKNOWN_RUBRIC_POINT",
            )
        points = round(
            answer["max_points"] * sum(rubric[p] for p in chosen) / sum(rubric.values()), 2
        )
        feedback = {**answer["feedback"], "matched_point_ids": chosen}
        await connection.execute(
            "update public.quiz_answers set grading_method = 'self_review', points_awarded = %s,"
            " feedback = %s, graded_at = now() where id = %s and user_id = %s",
            (points, Jsonb(feedback), answer_id, user_id),
        )
        await finalize_attempt(
            connection, user_id=user_id, attempt_id=answer["attempt_id"], config=config
        )
        log.info("quiz.answer_reviewed", answer_id=str(answer_id), met=len(chosen))
        return answer["attempt_id"]
