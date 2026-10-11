"""Builders for lesson tests: a context, a draft that satisfies it, and a seeded learning state."""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.ai.fake_lesson import sample_lesson
from app.ai.lesson.context import LessonContext
from app.ai.lesson.schema import DraftLesson, Lesson
from app.ai.lesson.validation import build_lesson
from support.database import create_auth_user
from support.rows import add_goal, add_item, add_job, add_module, add_roadmap


def make_context(**overrides: Any) -> LessonContext:
    values: dict[str, Any] = {
        "goal_title": "Learn the Rust programming language",
        "goal_type": "professional_skill",
        "level": "beginner",
        "language": "en",
        "learning_preferences": ("examples", "quizzes"),
        "topic_title": "Ownership and borrowing",
        "topic_description": "How Rust manages memory without a garbage collector.",
        "practice_task": "Write a function that borrows a string and returns its length.",
        "estimated_minutes": 30,
        "module_title": "Core ideas",
        "module_summary": "The ideas everything else rests on.",
        "objectives": ("Explain what ownership means",),
        "already_covered": ("Installing Rust",),
        "coming_next": ("Lifetimes",),
        "syllabus_basis": "general_knowledge",
    }
    values.update(overrides)
    return LessonContext(**values)


def valid_draft(context: LessonContext | None = None) -> DraftLesson:
    """A draft that passes every check for ``context`` (the built-in sample lesson)."""
    return sample_lesson((context or make_context()).input_data())


def valid_lesson(context: LessonContext | None = None) -> Lesson:
    lesson, violations = build_lesson(valid_draft(context))
    assert lesson is not None and violations == [], violations
    return lesson


def changed(draft: DraftLesson, edit: Callable[[dict[str, Any]], None]) -> DraftLesson:
    """A copy of ``draft`` after ``edit`` modified its plain-data form."""
    data = draft.model_dump()
    edit(data)
    return DraftLesson.model_validate(data)


@dataclass(frozen=True)
class Seeded:
    """One learner with a goal and a current roadmap whose items are all in the database."""

    user: uuid.UUID
    goal: uuid.UUID
    roadmap: uuid.UUID
    module: uuid.UUID
    topics: tuple[uuid.UUID, ...]
    revision: uuid.UUID
    extra: uuid.UUID


def seed_learning_state(dsn: str, *, topics: int = 3, **goal_fields: Any) -> Seeded:
    """A learner, a goal, a completed roadmap job and the roadmap it produced, with ``topics``
    topics, one revision session and one optional extra, written straight to the database."""
    user = create_auth_user(dsn)
    goal = add_goal(dsn, user, **goal_fields)
    roadmap_job = add_job(dsn, user, goal, status="completed")
    roadmap = add_roadmap(dsn, user, goal, roadmap_job, topic_count=topics)
    module = add_module(dsn, user, roadmap)
    topic_ids = tuple(
        add_item(
            dsn,
            user,
            roadmap,
            module_id=module,
            position=n,
            key=f"topic-{n}",
            day=n,
            title=f"Topic {n}",
        )
        for n in range(1, topics + 1)
    )
    revision = add_item(
        dsn,
        user,
        roadmap,
        module_id=None,
        kind="revision",
        position=topics + 1,
        key="revise",
        day=topics + 1,
        title="Revision",
    )
    extra = add_item(
        dsn,
        user,
        roadmap,
        module_id=None,
        kind="enrichment",
        position=topics + 2,
        key="extra",
        day=None,
        title="Optional extra",
    )
    return Seeded(user, goal, roadmap, module, topic_ids, revision, extra)


def add_lesson_job(
    dsn: str, seeded: Seeded, item: uuid.UUID, *, status: str = "queued", **fields: Any
) -> uuid.UUID:
    """A lesson job for ``item``, in ``status``."""
    return add_job(
        dsn,
        seeded.user,
        seeded.goal,
        status=status,
        job_type="lesson",
        item_id=item,
        **fields,
    )
