"""A learner's progress through a goal's roadmap: mastery per topic and the one next step.

Everything here reads the learner's own rows (row security) and turns them into the pure inputs of
``app.learning``: the scoring and the recommendation are not decided in this module.
"""

from uuid import UUID

from app.core.config import Settings
from app.core.db import UserConnection
from app.core.errors import NotFoundError
from app.core.security import Principal
from app.learning.mastery import MasteryConfig, MasteryResult, ObjectiveScore
from app.learning.recommend import Recommendation, TopicState, recommend
from app.repositories import goals as goals_repo
from app.repositories import lessons as lessons_repo
from app.repositories import quizzes as quizzes_repo
from app.repositories import roadmaps as roadmaps_repo
from app.schemas.quizzes import (
    GoalProgress,
    ProgressCounts,
    RecommendationOut,
    TopicMasteryOut,
    TopicProgress,
)


def mastery_config(settings: Settings) -> MasteryConfig:
    return MasteryConfig.from_settings(settings)


def _result(mastery: TopicMasteryOut) -> MasteryResult:
    return MasteryResult(
        score=mastery.score,
        band=mastery.band,
        attempts=mastery.attempts_count,
        answers=mastery.answers_count,
        low_confidence=mastery.low_confidence,
        objectives=tuple(ObjectiveScore(o.id, o.score, o.answers) for o in mastery.objectives),
    )


def recommendation_out(
    recommendation: Recommendation, titles: dict[UUID, str], objective_texts: dict[str, str]
) -> RecommendationOut:
    return RecommendationOut(
        action=recommendation.action,
        reason=recommendation.reason,
        item_id=recommendation.item_id,
        item_title=titles.get(recommendation.item_id) if recommendation.item_id else None,
        quiz_id=recommendation.quiz_id,
        objective_ids=list(recommendation.objective_ids),
        objective_texts=[
            objective_texts[oid] for oid in recommendation.objective_ids if oid in objective_texts
        ],
        review_lesson=recommendation.review_lesson,
    )


async def goal_progress(
    connection: UserConnection, principal: Principal, goal_id: UUID, *, settings: Settings
) -> GoalProgress:
    """Every topic of the goal's current roadmap with its mastery, and the recommended next step."""
    goal = await goals_repo.get(connection, principal.user_id, goal_id)
    if goal is None:
        raise NotFoundError("Goal not found.", code="GOAL_NOT_FOUND")
    roadmap_id = await roadmaps_repo.get_current_id(connection, principal.user_id, goal_id)
    if roadmap_id is None:
        return GoalProgress(
            goal_id=goal_id,
            roadmap_id=None,
            topics=[],
            counts=ProgressCounts(
                total=0, mastered=0, progressing=0, needs_practice=0, not_assessed=0
            ),
            recommendation=None,
        )
    return await roadmap_progress(
        connection, principal, goal_id=goal_id, roadmap_id=roadmap_id, settings=settings
    )


async def roadmap_progress(
    connection: UserConnection,
    principal: Principal,
    *,
    goal_id: UUID,
    roadmap_id: UUID,
    settings: Settings,
) -> GoalProgress:
    user_id = principal.user_id
    outline = await lessons_repo.outline(connection, user_id, roadmap_id)
    mastery = await quizzes_repo.mastery_for_roadmap(
        connection, user_id, roadmap_id, mastery_config(settings)
    )
    pending = await quizzes_repo.pending_quiz_ids(connection, user_id, roadmap_id)
    attempts = await quizzes_repo.last_attempts(connection, user_id, roadmap_id)
    texts = await quizzes_repo.objective_texts(connection, user_id, roadmap_id)

    topics = [
        TopicProgress(
            item_id=entry.item_id,
            title=entry.title,
            module_title=entry.module_title,
            kind=entry.kind,
            study=entry.study,
            mastery=mastery.get(entry.item_id),
            pending_quiz_id=pending.get(entry.item_id),
            last_attempt=attempts.get(entry.item_id),
        )
        for entry in outline
    ]
    core = [topic for topic in topics if topic.kind == "topic"]
    counts = ProgressCounts(
        total=len(core),
        mastered=sum(1 for t in core if t.mastery and t.mastery.band == "mastered"),
        progressing=sum(1 for t in core if t.mastery and t.mastery.band == "progressing"),
        needs_practice=sum(1 for t in core if t.mastery and t.mastery.band == "needs_practice"),
        not_assessed=sum(1 for t in core if t.mastery is None),
    )
    states = [
        TopicState(
            item_id=t.item_id,
            title=t.title,
            study=t.study.status,
            has_lesson=t.study.has_lesson,
            mastery=_result(t.mastery) if t.mastery else None,
            pending_quiz_id=t.pending_quiz_id,
        )
        for t in core
    ]
    recommendation = recommend(states, mastery_config(settings)) if states else None
    return GoalProgress(
        goal_id=goal_id,
        roadmap_id=roadmap_id,
        topics=topics,
        counts=counts,
        recommendation=recommendation_out(
            recommendation, {t.item_id: t.title for t in topics}, texts
        )
        if recommendation
        else None,
    )
