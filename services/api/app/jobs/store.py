"""Reading goals and writing finished roadmaps, for the worker (privileged connection).

``save_roadmap`` is the only place a roadmap is created. It runs in ONE transaction that

1. confirms this worker still owns the job (and the learner has not cancelled it),
2. locks the goal, which serialises version numbers and refuses archived or deleted goals,
3. returns the existing roadmap if this job already stored one (a retry after a crash),
4. demotes the current version and stores the new one with its modules, items and prerequisites,
5. marks the job completed,

so a plan is either fully stored and the job finished, or nothing changed at all.
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from app.ai.roadmap.context import OutlineModule, OutlineTopic
from app.ai.roadmap.schema import PlannedRoadmap, PlanTopic
from app.core.db import SystemConnection
from app.jobs import queue
from app.jobs.errors import JobCancelled, JobFailure, LeaseLost
from app.jobs.queue import Job
from app.schemas.goals import Goal

_GOAL_COLUMNS = """
    id, title, description, goal_type, current_level, target_date, daily_minutes,
    preferred_languages, learning_preferences, status, completed_at, archived_at,
    created_at, updated_at
"""


@dataclass(frozen=True)
class PlanMeta:
    """How and with what a plan was produced; stored with it."""

    prompt_version: str
    provider: str
    model_id: str
    synthetic: bool
    total_minutes: int
    total_days: int
    topic_count: int


@dataclass(frozen=True)
class SavedRoadmap:
    id: UUID
    version: int


async def load_goal(connection: SystemConnection, user_id: UUID, goal_id: UUID) -> Goal | None:
    cursor = await connection.execute(
        f"select {_GOAL_COLUMNS} from public.learning_goals where id = %s and user_id = %s",  # noqa: S608
        (goal_id, user_id),
    )
    row = await cursor.fetchone()
    return Goal.model_validate(row) if row else None


async def verify_base(
    connection: SystemConnection, user_id: UUID, goal_id: UUID, roadmap_id: UUID
) -> UUID | None:
    """``roadmap_id`` if it is one of this learner's roadmaps for this goal, else None.

    A job's request is data; it never gets to point a revision at someone else's plan.
    """
    cursor = await connection.execute(
        "select id from public.roadmaps where id = %s and user_id = %s and goal_id = %s",
        (roadmap_id, user_id, goal_id),
    )
    row = await cursor.fetchone()
    return row["id"] if row else None


async def load_outline(
    connection: SystemConnection, user_id: UUID, roadmap_id: UUID
) -> tuple[OutlineModule, ...] | None:
    """A roadmap's modules and topics in study order, for a revision prompt."""
    cursor = await connection.execute(
        "select m.position as module_position, m.title as module_title, i.title,"
        " i.estimated_minutes, i.day_number"
        " from public.roadmap_items i join public.roadmap_modules m on m.id = i.module_id"
        " where i.roadmap_id = %s and i.user_id = %s and i.kind = 'topic'"
        " order by m.position, i.position",
        (roadmap_id, user_id),
    )
    modules: dict[int, tuple[str, list[OutlineTopic]]] = {}
    for row in await cursor.fetchall():
        _, topics = modules.setdefault(row["module_position"], (row["module_title"], []))
        topics.append(OutlineTopic(row["title"], row["estimated_minutes"], row["day_number"]))
    if not modules:
        return None
    return tuple(
        OutlineModule(title, tuple(topics)) for _, (title, topics) in sorted(modules.items())
    )


async def save_roadmap(
    connection: SystemConnection,
    job: Job,
    worker_id: str,
    *,
    plan: PlannedRoadmap,
    meta: PlanMeta,
    goal: Goal,
    feedback: str | None,
    based_on: UUID | None,
) -> SavedRoadmap:
    """Store ``plan`` as the goal's newest version and finish the job. Call inside one session."""
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

    cursor = await connection.execute(
        "select status from public.learning_goals where id = %s and user_id = %s for update",
        (job.goal_id, job.user_id),
    )
    locked_goal = await cursor.fetchone()
    if locked_goal is None or locked_goal["status"] == "archived":
        raise JobFailure(
            "GOAL_UNAVAILABLE", "This goal was archived or deleted before the plan was ready."
        )

    cursor = await connection.execute(
        "select id, version from public.roadmaps where job_id = %s", (job.id,)
    )
    existing = await cursor.fetchone()
    if existing is not None:  # a retry after a crash between "stored" and "marked complete"
        await queue.complete(connection, job.id, worker_id)
        return SavedRoadmap(id=existing["id"], version=existing["version"])

    cursor = await connection.execute(
        "select coalesce(max(version), 0) + 1 as next from public.roadmaps where goal_id = %s",
        (job.goal_id,),
    )
    version_row = await cursor.fetchone()
    if version_row is None:
        raise RuntimeError("version query returned no row")
    version: int = version_row["next"]

    await connection.execute(
        "update public.roadmaps set status = 'superseded'"
        " where goal_id = %s and user_id = %s and status = 'current'",
        (job.goal_id, job.user_id),
    )
    roadmap_id = await _insert_roadmap(
        connection, job, plan, meta, goal, version, feedback, based_on
    )
    await _insert_contents(connection, job.user_id, roadmap_id, plan)
    if not await queue.complete(connection, job.id, worker_id):
        raise LeaseLost  # rolls the whole transaction back
    return SavedRoadmap(id=roadmap_id, version=version)


async def _insert_roadmap(
    connection: SystemConnection,
    job: Job,
    plan: PlannedRoadmap,
    meta: PlanMeta,
    goal: Goal,
    version: int,
    feedback: str | None,
    based_on: UUID | None,
) -> UUID:
    cursor = await connection.execute(
        """
        insert into public.roadmaps
            (user_id, goal_id, job_id, version, status, title, overview, target_outcome, language,
             syllabus_basis, assumptions, unknowns, objectives, evidence, total_minutes,
             total_days, topic_count, daily_minutes, target_date, revision_feedback,
             based_on_roadmap_id, prompt_version, provider, model_id, is_synthetic)
        values
            (%(user_id)s, %(goal_id)s, %(job_id)s, %(version)s, 'current', %(title)s, %(overview)s,
             %(target_outcome)s, %(language)s, %(syllabus_basis)s, %(assumptions)s, %(unknowns)s,
             %(objectives)s, %(evidence)s, %(total_minutes)s, %(total_days)s, %(topic_count)s,
             %(daily_minutes)s, %(target_date)s, %(feedback)s, %(based_on)s, %(prompt_version)s,
             %(provider)s, %(model_id)s, %(synthetic)s)
        returning id
        """,
        {
            "user_id": job.user_id,
            "goal_id": job.goal_id,
            "job_id": job.id,
            "version": version,
            "title": plan.title,
            "overview": plan.overview,
            "target_outcome": plan.target_outcome,
            "language": plan.language,
            "syllabus_basis": plan.syllabus_basis,
            "assumptions": plan.assumptions,
            "unknowns": plan.unknowns,
            "objectives": Jsonb([o.model_dump() for o in plan.objectives]),
            "evidence": Jsonb([e.model_dump() for e in plan.evidence]),
            "total_minutes": meta.total_minutes,
            "total_days": meta.total_days,
            "topic_count": meta.topic_count,
            "daily_minutes": goal.daily_minutes,
            "target_date": goal.target_date,
            "feedback": feedback,
            "based_on": based_on,
            "prompt_version": meta.prompt_version,
            "provider": meta.provider,
            "model_id": meta.model_id,
            "synthetic": meta.synthetic,
        },
    )
    row = await cursor.fetchone()
    if row is None:
        raise RuntimeError("roadmap insert returned no row")
    return row["id"]


async def _insert_contents(
    connection: SystemConnection, user_id: UUID, roadmap_id: UUID, plan: PlannedRoadmap
) -> None:
    """Modules, then topics, revision sessions and enrichment, then the prerequisite links."""
    item_ids: dict[str, UUID] = {}
    position = 0

    async def insert_item(
        *,
        module_id: UUID | None,
        kind: str,
        key: str,
        title: str,
        description: str,
        practice_task: str | None,
        objective_ids: list[str],
        minutes: int,
        day: int | None,
    ) -> None:
        nonlocal position
        position += 1
        cursor = await connection.execute(
            "insert into public.roadmap_items (user_id, roadmap_id, module_id, kind, position,"
            " item_key, title, description, practice_task, objective_ids, estimated_minutes,"
            " day_number) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) returning id",
            (
                user_id,
                roadmap_id,
                module_id,
                kind,
                position,
                key,
                title,
                description,
                practice_task,
                objective_ids,
                minutes,
                day,
            ),
        )
        row = await cursor.fetchone()
        if row is None:
            raise RuntimeError("item insert returned no row")
        item_ids[key] = row["id"]

    topics_by_key: dict[str, PlanTopic] = {}
    for module_position, module in enumerate(plan.modules, start=1):
        cursor = await connection.execute(
            "insert into public.roadmap_modules (user_id, roadmap_id, position, title, summary)"
            " values (%s, %s, %s, %s, %s) returning id",
            (user_id, roadmap_id, module_position, module.title, module.summary),
        )
        module_row = await cursor.fetchone()
        if module_row is None:
            raise RuntimeError("module insert returned no row")
        for topic in module.topics:
            topics_by_key[topic.key] = topic
            await insert_item(
                module_id=module_row["id"],
                kind="topic",
                key=topic.key,
                title=topic.title,
                description=topic.description,
                practice_task=topic.practice_task,
                objective_ids=topic.objective_ids,
                minutes=topic.estimated_minutes,
                day=topic.day,
            )

    for session in sorted(plan.revision_sessions, key=lambda s: (s.day, s.key)):
        await insert_item(
            module_id=None,
            kind="revision",
            key=session.key,
            title=session.title,
            description=session.task,
            practice_task=None,
            objective_ids=[],
            minutes=session.estimated_minutes,
            day=session.day,
        )
    for extra in plan.enrichment:
        await insert_item(
            module_id=None,
            kind="enrichment",
            key=extra.key,
            title=extra.title,
            description=extra.description,
            practice_task=None,
            objective_ids=[],
            minutes=extra.estimated_minutes,
            day=None,
        )

    links: list[tuple[str, str]] = [
        (topic.key, prerequisite)
        for topic in topics_by_key.values()
        for prerequisite in topic.prerequisite_keys
    ]
    links += [(s.key, topic_key) for s in plan.revision_sessions for topic_key in s.revisits]
    seen: set[tuple[str, str]] = set()
    for item_key, prerequisite_key in links:
        if (item_key, prerequisite_key) in seen:
            continue  # the model listed the same link twice
        seen.add((item_key, prerequisite_key))
        await connection.execute(
            "insert into public.roadmap_item_prerequisites"
            " (item_id, prerequisite_id, roadmap_id, user_id) values (%s, %s, %s, %s)",
            (item_ids[item_key], item_ids[prerequisite_key], roadmap_id, user_id),
        )


def checkpoint_of(plan: PlannedRoadmap, meta: PlanMeta) -> dict[str, Any]:
    """What a retry needs to skip the (paid) planning step."""
    return {
        "plan": plan.model_dump(),
        "meta": {
            "prompt_version": meta.prompt_version,
            "provider": meta.provider,
            "model_id": meta.model_id,
            "synthetic": meta.synthetic,
            "total_minutes": meta.total_minutes,
            "total_days": meta.total_days,
            "topic_count": meta.topic_count,
        },
    }


def restore_checkpoint(checkpoint: dict[str, Any]) -> tuple[PlannedRoadmap, PlanMeta]:
    plan = PlannedRoadmap.model_validate(checkpoint["plan"])
    return plan, PlanMeta(**checkpoint["meta"])
