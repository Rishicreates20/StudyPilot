"""The built-in answer of ``FakeProvider`` to a roadmap request.

It builds a small, always-valid plan from the same facts the real prompt is rendered from, and it
says so in the plan itself: the overview, the assumptions and the stored ``is_synthetic`` flag all
state that this is a sample from the test provider and not AI-generated content. It exists so the
whole pipeline (queue, worker, validation, storage, UI) can be exercised without a model or a key.
"""

from collections.abc import Mapping
from typing import Any

from app.ai.fake import Reply
from app.ai.provider import StructuredRequest
from app.ai.roadmap.schema import (
    PlanEnrichment,
    PlanModule,
    PlannedRoadmap,
    PlanObjective,
    PlanRevision,
    PlanTopic,
)

_SAMPLE_NOTE = "This is a sample plan from the built-in test provider, not an AI-generated one."
_MAX_TOPICS = 6
_EXAM_LIKE = frozenset({"exam", "certification"})


def sample_plan(input_data: Mapping[str, Any]) -> PlannedRoadmap:
    goal: Mapping[str, Any] = input_data["goal"]
    schedule: Mapping[str, Any] = input_data["schedule"]
    languages: list[str] = list(input_data["languages"])
    preferences: list[str] = list(input_data["learning_preferences"])
    feedback: str | None = input_data.get("revision_feedback")

    title = str(goal["title"]).strip()
    daily = int(schedule["daily_minutes"])
    max_days = int(schedule["max_days"])
    wants_revision = "revision" in preferences

    # One topic a day, then (if there is room and the learner wants it) one revision day.
    reserve = 1 if wants_revision and max_days >= 3 else 0
    count = max(1, min(_MAX_TOPICS, max_days - reserve))
    topic_minutes = min(40, daily)
    objective_count = min(3, count)

    objectives = [
        PlanObjective(id=f"o{n + 1}", text=f"Understand part {n + 1} of {title[:80]}")
        for n in range(objective_count)
    ]
    topics = [
        PlanTopic(
            key=f"part-{n + 1}",
            title=f"Part {n + 1}: {title[:60]}",
            description=f"Sample topic {n + 1} for the goal. Replace it with a real plan later.",
            objective_ids=[f"o{(n % objective_count) + 1}"],
            prerequisite_keys=[f"part-{n}"] if n else [],
            estimated_minutes=topic_minutes,
            day=n + 1,
            practice_task=f"Write three questions about part {n + 1} and answer them.",
        )
        for n in range(count)
    ]
    split = (count + 1) // 2 if count > 1 else count
    modules = [
        PlanModule(
            title="Foundations", summary="The first half of the sample plan.", topics=topics[:split]
        )
    ]
    if topics[split:]:
        modules.append(
            PlanModule(
                title="Going further",
                summary="The second half of the sample plan.",
                topics=topics[split:],
            )
        )

    revisions: list[PlanRevision] = []
    if wants_revision and count + 1 <= max_days and count >= 2:
        revisions.append(
            PlanRevision(
                key="review-everything",
                title="Review the sample topics",
                day=count + 1,
                estimated_minutes=min(20, daily),
                revisits=[topic.key for topic in topics],
                task="Without notes, explain each part aloud, then check your answers.",
            )
        )

    assumptions = [_SAMPLE_NOTE]
    if feedback:
        assumptions.append(f"A revision was requested: {feedback[:120]}")
    unknowns = (
        ["The official syllabus, exam pattern and dates were not provided and are not verified."]
        if goal["type"] in _EXAM_LIKE
        else []
    )
    return PlannedRoadmap(
        language=languages[0],
        title=f"Sample plan: {title}"[:200],
        overview=(
            f"{_SAMPLE_NOTE} It has {count} short topics, one per day, to show how a roadmap looks."
        ),
        target_outcome=f"Be able to explain the main ideas of {title[:100]}.",
        syllabus_basis="learner_stated",
        assumptions=assumptions,
        unknowns=unknowns,
        objectives=objectives,
        modules=modules,
        revision_sessions=revisions,
        enrichment=[
            PlanEnrichment(
                key="explore-more",
                title="Explore further (optional)",
                description="An optional extra topic that is not part of the scheduled plan.",
                estimated_minutes=min(30, daily),
            )
        ],
    )


def roadmap_responder(request: StructuredRequest) -> Reply:
    return sample_plan(request.input_data)
