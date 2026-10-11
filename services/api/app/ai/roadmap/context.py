"""The facts a roadmap is planned from, and the checks that a goal is plannable at all."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.schemas.goals import Goal

MIN_TITLE_CHARS = 3
# Less than this between today and the target date is not a plan, however small the topics.
MIN_PLAN_MINUTES = 60
# Without a target date a plan may run up to a year; the model is told to choose a realistic length.
DEFAULT_HORIZON_DAYS = 365
_MAX_OUTLINE_MODULES = 12
_MAX_OUTLINE_TOPICS = 80


@dataclass(frozen=True)
class OutlineTopic:
    title: str
    estimated_minutes: int
    day: int


@dataclass(frozen=True)
class OutlineModule:
    title: str
    topics: tuple[OutlineTopic, ...]


@dataclass(frozen=True)
class PlanningContext:
    """Everything the planner and the validator both need. Built once per job."""

    goal_title: str
    goal_description: str | None
    goal_type: str
    level: str
    daily_minutes: int
    languages: tuple[str, ...]
    learning_preferences: tuple[str, ...]
    today: date
    target_date: date | None
    # The last study day the plan may use (day 1 is today).
    max_days: int
    # (source_id, chunk_id) pairs of the learner's own material the plan may cite. Empty until
    # document upload exists.
    evidence_ids: frozenset[tuple[str, str]] = frozenset()
    feedback: str | None = None
    previous_outline: tuple[OutlineModule, ...] | None = None
    target_date_passed: bool = False
    extra: dict[str, Any] = field(default_factory=lambda: {})

    def input_data(self) -> dict[str, Any]:
        """The facts as plain data: rendered into the prompt, and used by the test double."""
        return {
            "goal": {
                "title": self.goal_title,
                "description": self.goal_description,
                "type": self.goal_type,
                "current_level": self.level,
            },
            "schedule": {
                "today": self.today.isoformat(),
                "target_date": self.target_date.isoformat() if self.target_date else None,
                "target_date_passed": self.target_date_passed,
                "daily_minutes": self.daily_minutes,
                "max_days": self.max_days,
            },
            "languages": list(self.languages),
            "learning_preferences": list(self.learning_preferences),
            "has_uploaded_material": bool(self.evidence_ids),
            "revision_feedback": self.feedback,
            "previous_plan": (
                [
                    {
                        "module": module.title,
                        "topics": [
                            {"title": t.title, "minutes": t.estimated_minutes, "day": t.day}
                            for t in module.topics
                        ],
                    }
                    for module in self.previous_outline
                ]
                if self.previous_outline
                else None
            ),
        }


def days_available(target_date: date | None, today: date) -> int | None:
    """Study days from ``today`` to ``target_date`` inclusive; None if there is no usable date."""
    if target_date is None or target_date < today:
        return None
    return (target_date - today).days + 1


def readiness_problems(goal: Goal, today: date) -> list[str]:
    """Reasons this goal cannot be planned yet, in words a learner can act on. Empty = fine."""
    problems: list[str] = []
    if len(goal.title.strip()) < MIN_TITLE_CHARS:
        problems.append("Give the goal a more descriptive title before generating a roadmap.")
    days = days_available(goal.target_date, today)
    if days is not None and days * goal.daily_minutes < MIN_PLAN_MINUTES:
        problems.append(
            f"Your target date leaves about {days * goal.daily_minutes} minutes of study "
            f"({days} day{'s' if days != 1 else ''} at {goal.daily_minutes} minutes a day), "
            f"which is too little for a plan. Move the date later or raise the daily minutes."
        )
    return problems


def build_context(
    goal: Goal,
    *,
    today: date,
    evidence_ids: frozenset[tuple[str, str]] = frozenset(),
    feedback: str | None = None,
    previous_outline: Sequence[OutlineModule] | None = None,
) -> PlanningContext:
    days = days_available(goal.target_date, today)
    return PlanningContext(
        goal_title=goal.title,
        goal_description=goal.description,
        goal_type=goal.goal_type,
        level=goal.current_level,
        daily_minutes=goal.daily_minutes,
        languages=tuple(goal.preferred_languages),
        learning_preferences=tuple(goal.learning_preferences),
        today=today,
        target_date=goal.target_date if days is not None else None,
        max_days=min(days, DEFAULT_HORIZON_DAYS) if days is not None else DEFAULT_HORIZON_DAYS,
        evidence_ids=evidence_ids,
        feedback=feedback,
        previous_outline=(
            tuple(previous_outline)[:_MAX_OUTLINE_MODULES] if previous_outline else None
        ),
        target_date_passed=goal.target_date is not None and days is None,
    )


def outline_of(modules: Sequence[OutlineModule]) -> tuple[OutlineModule, ...]:
    """Trim a previous plan to a size that is sensible to put in a prompt."""
    remaining = _MAX_OUTLINE_TOPICS
    trimmed: list[OutlineModule] = []
    for module in modules[:_MAX_OUTLINE_MODULES]:
        topics = module.topics[:remaining]
        remaining -= len(topics)
        if topics:
            trimmed.append(OutlineModule(title=module.title, topics=topics))
        if remaining <= 0:
            break
    return tuple(trimmed)
