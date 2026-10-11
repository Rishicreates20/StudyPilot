"""Recomputing a topic's stored mastery from the answers underneath it.

``topic_mastery`` is only a cache of ``compute_mastery`` over the graded answers: it can be deleted
and rebuilt at any time, and when the method changes (a new ``ALGORITHM_VERSION``) every topic can
be recomputed from the stored attempts without losing anything. Privileged: it runs inside the
grading transaction and filters by ``user_id`` and ``item_id`` explicitly.
"""

from uuid import UUID

from psycopg.types.json import Jsonb

from app.core.db import SystemConnection
from app.learning.mastery import (
    ALGORITHM_VERSION,
    AnsweredQuestion,
    MasteryConfig,
    MasteryResult,
    compute_mastery,
)


async def recompute_mastery(
    connection: SystemConnection, *, user_id: UUID, item_id: UUID, config: MasteryConfig
) -> MasteryResult | None:
    """Rebuild this topic's mastery row from its graded answers (None, and no row, if none)."""
    cursor = await connection.execute(
        "select a.id as attempt_id, qa.points_awarded, qa.max_points, q.objective_id"
        " from public.quiz_answers qa"
        " join public.quiz_attempts a on a.id = qa.attempt_id and a.user_id = qa.user_id"
        " join public.quizzes z on z.id = a.quiz_id and z.user_id = a.user_id"
        " join public.questions q on q.id = qa.question_id and q.user_id = qa.user_id"
        " where z.item_id = %s and a.user_id = %s and a.status = 'graded'"
        "   and qa.grading_method <> 'pending'"
        " order by a.submitted_at desc, a.id",
        (item_id, user_id),
    )
    rows = await cursor.fetchall()
    ranks: dict[UUID, int] = {}
    answers: list[AnsweredQuestion] = []
    for row in rows:
        rank = ranks.setdefault(row["attempt_id"], len(ranks))
        answers.append(
            AnsweredQuestion(
                attempt_rank=rank,
                objective_id=row["objective_id"],
                possible=row["max_points"],
                earned=float(row["points_awarded"]),
            )
        )
    result = compute_mastery(answers, config)
    if result is None:
        await connection.execute(
            "delete from public.topic_mastery where item_id = %s and user_id = %s",
            (item_id, user_id),
        )
        return None

    await connection.execute(
        "insert into public.topic_mastery (item_id, user_id, roadmap_id, score, band,"
        " attempts_count, answers_count, low_confidence, objectives, algorithm_version,"
        " computed_at)"
        " select i.id, %(user)s, i.roadmap_id, %(score)s, %(band)s, %(attempts)s, %(answers)s,"
        "        %(low)s, %(objectives)s, %(version)s, now()"
        " from public.roadmap_items i where i.id = %(item)s and i.user_id = %(user)s"
        " on conflict (item_id) do update set score = excluded.score, band = excluded.band,"
        "   attempts_count = excluded.attempts_count, answers_count = excluded.answers_count,"
        "   low_confidence = excluded.low_confidence, objectives = excluded.objectives,"
        "   algorithm_version = excluded.algorithm_version, computed_at = now()",
        {
            "item": item_id,
            "user": user_id,
            "score": result.score,
            "band": result.band,
            "attempts": result.attempts,
            "answers": result.answers,
            "low": result.low_confidence,
            "objectives": Jsonb(
                [{"id": o.id, "score": o.score, "answers": o.answers} for o in result.objectives]
            ),
            "version": ALGORITHM_VERSION,
        },
    )
    return result
