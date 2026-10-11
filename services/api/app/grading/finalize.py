"""Closing an attempt once every answer in it has a result, and refreshing the topic's mastery."""

from uuid import UUID

from app.core.db import SystemConnection
from app.grading.mastery_store import recompute_mastery
from app.learning.mastery import MasteryConfig


async def finalize_attempt(
    connection: SystemConnection, *, user_id: UUID, attempt_id: UUID, config: MasteryConfig
) -> bool:
    """Total the attempt and mark it graded if no answer is still pending.

    Safe to call again after a result changes (a learner's review): the totals are recomputed from
    the answers every time, so they can never drift from them. Returns whether the attempt is
    graded.
    """
    cursor = await connection.execute(
        "select count(*) filter (where grading_method = 'pending') as pending,"
        " coalesce(sum(points_awarded), 0) as earned, coalesce(sum(max_points), 0) as possible"
        " from public.quiz_answers where attempt_id = %s and user_id = %s",
        (attempt_id, user_id),
    )
    totals = await cursor.fetchone()
    if totals is None or totals["pending"] > 0 or totals["possible"] <= 0:
        return False

    earned = float(totals["earned"])
    possible = int(totals["possible"])
    cursor = await connection.execute(
        "update public.quiz_attempts set status = 'graded',"
        " graded_at = coalesce(graded_at, now()), points_earned = %s, points_possible = %s,"
        " percent = %s where id = %s and user_id = %s returning quiz_id",
        (round(earned, 2), possible, round(100.0 * earned / possible, 2), attempt_id, user_id),
    )
    attempt = await cursor.fetchone()
    if attempt is None:
        return False
    cursor = await connection.execute(
        "select item_id from public.quizzes where id = %s and user_id = %s",
        (attempt["quiz_id"], user_id),
    )
    quiz = await cursor.fetchone()
    if quiz is not None:
        await recompute_mastery(connection, user_id=user_id, item_id=quiz["item_id"], config=config)
    return True
