"""Insert rows directly (as the database owner) so database tests can set up any state."""

import uuid
from collections.abc import Mapping
from typing import Any, LiteralString, cast

from psycopg import sql

from support.database import admin


def _insert(
    dsn: str, table: str, values: Mapping[str, Any], raw: Mapping[str, str] | None = None
) -> uuid.UUID:
    """Insert one row and return its id. ``raw`` holds SQL expressions (such as ``now()``)."""
    raw = raw or {}
    names = [*values, *raw]
    query = sql.SQL("insert into public.{table} ({columns}) values ({values}) returning id").format(
        table=sql.Identifier(table),
        columns=sql.SQL(", ").join(sql.Identifier(n) for n in names),
        values=sql.SQL(", ").join(
            [
                *(sql.Placeholder() for _ in values),
                *(sql.SQL(cast(LiteralString, raw[n])) for n in raw),
            ]
        ),
    )
    row = admin(dsn).fetchone(query, list(values.values()))
    assert row is not None
    return row["id"]


def add_goal(dsn: str, user_id: uuid.UUID, *, status: str = "active", **fields: Any) -> uuid.UUID:
    """A goal for ``user_id``; every state is one legal step from ``active``."""
    goal_id = _insert(
        dsn, "learning_goals", {"user_id": user_id, "title": "Learn Kubernetes", **fields}
    )
    if status != "active":
        admin(dsn).execute(
            "update public.learning_goals set status = %s where id = %s", (status, goal_id)
        )
    return goal_id


def add_job(
    dsn: str, user_id: uuid.UUID, goal_id: uuid.UUID, *, status: str = "queued", **fields: Any
) -> uuid.UUID:
    """A generation job in ``status``, with the columns that status requires filled in."""
    values: dict[str, Any] = {
        "user_id": user_id,
        "goal_id": goal_id,
        "job_type": "roadmap",
        "status": status,
        **fields,
    }
    raw: dict[str, str] = {}
    if status == "running":
        values.setdefault("locked_by", "test-worker")
        if "locked_until" not in values:
            raw["locked_until"] = "now() + interval '1 minute'"
    if status in {"completed", "failed", "cancelled"} and "finished_at" not in values:
        raw["finished_at"] = "now()"
    if status == "failed":
        values.setdefault("error_code", "TEST_FAILURE")
    return _insert(dsn, "generation_jobs", values, raw)


def add_roadmap(
    dsn: str,
    user_id: uuid.UUID,
    goal_id: uuid.UUID,
    job_id: uuid.UUID,
    *,
    version: int = 1,
    status: str = "current",
    **fields: Any,
) -> uuid.UUID:
    return _insert(
        dsn,
        "roadmaps",
        {
            "user_id": user_id,
            "goal_id": goal_id,
            "job_id": job_id,
            "version": version,
            "status": status,
            "title": "Sample roadmap",
            "overview": "An overview of the plan.",
            "target_outcome": "Be able to do the thing.",
            "language": "en",
            "syllabus_basis": "general_knowledge",
            "objectives": '[{"id": "o1", "text": "Do the thing"}]',
            "total_minutes": 120,
            "total_days": 3,
            "topic_count": 3,
            "daily_minutes": 60,
            "prompt_version": "test/v1",
            "provider": "fake",
            "model_id": "fake-1",
            **fields,
        },
    )


def add_module(
    dsn: str, user_id: uuid.UUID, roadmap_id: uuid.UUID, *, position: int = 1
) -> uuid.UUID:
    return _insert(
        dsn,
        "roadmap_modules",
        {
            "user_id": user_id,
            "roadmap_id": roadmap_id,
            "position": position,
            "title": "Module",
            "summary": "A module",
        },
    )


def add_item(
    dsn: str,
    user_id: uuid.UUID,
    roadmap_id: uuid.UUID,
    *,
    module_id: uuid.UUID | None,
    kind: str = "topic",
    position: int = 1,
    key: str | None = None,
    day: int | None = 1,
    minutes: int = 30,
    title: str = "An item",
) -> uuid.UUID:
    return _insert(
        dsn,
        "roadmap_items",
        {
            "user_id": user_id,
            "roadmap_id": roadmap_id,
            "module_id": module_id,
            "kind": kind,
            "position": position,
            "item_key": key if key is not None else f"item-{position}",
            "title": title,
            "description": "Described",
            "practice_task": "Practise it" if kind == "topic" else None,
            "estimated_minutes": minutes,
            "day_number": day,
        },
    )


def add_lesson(
    dsn: str,
    user_id: uuid.UUID,
    roadmap_id: uuid.UUID,
    item_id: uuid.UUID,
    job_id: uuid.UUID,
    *,
    version: int = 1,
    status: str = "current",
    section_ids: list[str] | None = None,
    **fields: Any,
) -> uuid.UUID:
    """A stored lesson whose content is the built-in sample (a real, valid document)."""
    from psycopg.types.json import Jsonb

    from support.lessons import valid_lesson

    lesson = valid_lesson()
    return _insert(
        dsn,
        "lessons",
        {
            "user_id": user_id,
            "roadmap_id": roadmap_id,
            "item_id": item_id,
            "job_id": job_id,
            "version": version,
            "status": status,
            "title": lesson.title,
            "language": lesson.language,
            "content": Jsonb(lesson.model_dump(mode="json")),
            "content_version": 1,
            "section_ids": section_ids if section_ids is not None else lesson.section_ids(),
            "prompt_version": "test/v1",
            "provider": "fake",
            "model_id": "fake-1",
            **fields,
        },
    )
