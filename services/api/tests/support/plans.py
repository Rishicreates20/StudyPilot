"""Builders for roadmap tests: a planning context and a plan that satisfies it."""

from collections.abc import Callable
from datetime import date
from typing import Any

from app.ai.fake_roadmap import sample_plan
from app.ai.roadmap.context import PlanningContext
from app.ai.roadmap.schema import PlannedRoadmap

TODAY = date(2026, 10, 12)


def make_context(**overrides: Any) -> PlanningContext:
    values: dict[str, Any] = {
        "goal_title": "Learn the Rust programming language",
        "goal_description": "I know Python and want to write command-line tools.",
        "goal_type": "professional_skill",
        "level": "beginner",
        "daily_minutes": 60,
        "languages": ("en",),
        "learning_preferences": ("examples", "quizzes", "revision"),
        "today": TODAY,
        "target_date": None,
        "max_days": 30,
    }
    values.update(overrides)
    return PlanningContext(**values)


def valid_plan(context: PlanningContext | None = None) -> PlannedRoadmap:
    """A plan that passes every check for ``context`` (the built-in sample plan)."""
    return sample_plan((context or make_context()).input_data())


def changed(plan: PlannedRoadmap, edit: Callable[[dict[str, Any]], None]) -> PlannedRoadmap:
    """A copy of ``plan`` after ``edit`` modified its plain-data form."""
    data = plan.model_dump()
    edit(data)
    return PlannedRoadmap.model_validate(data)
