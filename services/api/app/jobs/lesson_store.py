"""Reading a topic's facts and writing finished lessons, for the worker (privileged connection).

``save_lesson`` is the only place a lesson is created. It runs in ONE transaction that

1. confirms this worker still owns the job (and the learner has not cancelled it),
2. locks the goal, which serialises version numbers and refuses archived or deleted goals,
3. returns the existing lesson if this job already stored one (a retry after a crash),
4. demotes the topic's current version and stores the new one,
5. marks the job completed,

so a lesson is either fully stored and the job finished, or nothing changed at all.
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from app.ai.lesson.context import TopicFacts
from app.ai.lesson.schema import CONTENT_VERSION, Adjust, Lesson
from app.core.db import SystemConnection
from app.jobs import queue
from app.jobs.errors import JobCancelled, JobFailure, LeaseLost
from app.jobs.queue import Job


@dataclass(frozen=True)
class LessonMeta:
    """How and with what a lesson was produced; stored with it."""

    prompt_version: str
    provider: str
    model_id: str
    synthetic: bool


@dataclass(frozen=True)
class SavedLesson:
    id: UUID
    version: int


async def load_topic(
    connection: SystemConnection, user_id: UUID, item_id: UUID
) -> TopicFacts | None:
    """The topic's own text, its roadmap's language and objectives, and its neighbours."""
    cursor = await connection.execute(
        """
        select i.id, i.roadmap_id, i.kind, i.position, i.title, i.description, i.practice_task,
               i.objective_ids, i.estimated_minutes, m.title as module_title,
               m.summary as module_summary, r.status as roadmap_status, r.language,
               r.syllabus_basis, r.objectives
        from public.roadmap_items i
        join public.roadmaps r on r.id = i.roadmap_id and r.user_id = i.user_id
        left join public.roadmap_modules m on m.id = i.module_id
        where i.id = %s and i.user_id = %s
        """,
        (item_id, user_id),
    )
    row = await cursor.fetchone()
    if row is None:
        return None

    objective_text: dict[str, str] = {o["id"]: o["text"] for o in row["objectives"]}
    objectives = tuple(
        objective_text[objective_id]
        for objective_id in row["objective_ids"]
        if objective_id in objective_text
    )
    cursor = await connection.execute(
        "select title, position < %s as earlier from public.roadmap_items"
        " where roadmap_id = %s and user_id = %s and kind <> 'revision' and id <> %s"
        " order by position",
        (row["position"], row["roadmap_id"], user_id, item_id),
    )
    others = await cursor.fetchall()
    return TopicFacts(
        item_id=row["id"],
        roadmap_id=row["roadmap_id"],
        roadmap_status=row["roadmap_status"],
        kind=row["kind"],
        title=row["title"],
        description=row["description"],
        practice_task=row["practice_task"],
        estimated_minutes=row["estimated_minutes"],
        module_title=row["module_title"],
        module_summary=row["module_summary"],
        objectives=objectives,
        language=row["language"],
        syllabus_basis=row["syllabus_basis"],
        earlier_titles=tuple(o["title"] for o in others if o["earlier"]),
        later_titles=tuple(o["title"] for o in others if not o["earlier"]),
    )


async def load_lesson(
    connection: SystemConnection, user_id: UUID, item_id: UUID, lesson_id: UUID
) -> Lesson | None:
    """A stored lesson of this topic, parsed and re-validated; None if it isn't theirs.

    A job's request is data: it never gets to point a revision at another topic or another learner.
    """
    cursor = await connection.execute(
        "select content from public.lessons where id = %s and user_id = %s and item_id = %s",
        (lesson_id, user_id, item_id),
    )
    row = await cursor.fetchone()
    return Lesson.model_validate(row["content"]) if row else None


async def save_lesson(
    connection: SystemConnection,
    job: Job,
    worker_id: str,
    *,
    facts: TopicFacts,
    lesson: Lesson,
    meta: LessonMeta,
    adjust: Adjust | None,
    feedback: str | None,
    based_on: UUID | None,
) -> SavedLesson:
    """Store ``lesson`` as the topic's newest version and finish the job (one session)."""
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
            "GOAL_UNAVAILABLE", "This goal was archived or deleted before the lesson was ready."
        )

    cursor = await connection.execute(
        "select id, version from public.lessons where job_id = %s", (job.id,)
    )
    existing = await cursor.fetchone()
    if existing is not None:  # a retry after a crash between "stored" and "marked complete"
        await queue.complete(connection, job.id, worker_id)
        return SavedLesson(id=existing["id"], version=existing["version"])

    cursor = await connection.execute(
        "select coalesce(max(version), 0) + 1 as next from public.lessons where item_id = %s",
        (facts.item_id,),
    )
    version_row = await cursor.fetchone()
    if version_row is None:
        raise RuntimeError("version query returned no row")
    version: int = version_row["next"]

    await connection.execute(
        "update public.lessons set status = 'superseded'"
        " where item_id = %s and user_id = %s and status = 'current'",
        (facts.item_id, job.user_id),
    )
    cursor = await connection.execute(
        """
        insert into public.lessons
            (user_id, roadmap_id, item_id, job_id, version, status, title, language, content,
             content_version, section_ids, adjust, revision_feedback, based_on_lesson_id,
             prompt_version, provider, model_id, is_synthetic)
        values
            (%(user_id)s, %(roadmap_id)s, %(item_id)s, %(job_id)s, %(version)s, 'current',
             %(title)s, %(language)s, %(content)s, %(content_version)s, %(section_ids)s,
             %(adjust)s, %(feedback)s, %(based_on)s, %(prompt_version)s, %(provider)s,
             %(model_id)s, %(synthetic)s)
        returning id
        """,
        {
            "user_id": job.user_id,
            "roadmap_id": facts.roadmap_id,
            "item_id": facts.item_id,
            "job_id": job.id,
            "version": version,
            "title": lesson.title,
            "language": lesson.language,
            "content": Jsonb(lesson.model_dump(mode="json")),
            "content_version": CONTENT_VERSION,
            "section_ids": lesson.section_ids(),
            "adjust": adjust,
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
        raise RuntimeError("lesson insert returned no row")
    if not await queue.complete(connection, job.id, worker_id):
        raise LeaseLost  # rolls the whole transaction back
    return SavedLesson(id=row["id"], version=version)


def checkpoint_of(lesson: Lesson, meta: LessonMeta) -> dict[str, Any]:
    """What a retry needs to skip the (paid) writing step."""
    return {
        "lesson": lesson.model_dump(mode="json"),
        "meta": {
            "prompt_version": meta.prompt_version,
            "provider": meta.provider,
            "model_id": meta.model_id,
            "synthetic": meta.synthetic,
        },
    }


def restore_checkpoint(checkpoint: dict[str, Any]) -> tuple[Lesson, LessonMeta]:
    return Lesson.model_validate(checkpoint["lesson"]), LessonMeta(**checkpoint["meta"])
