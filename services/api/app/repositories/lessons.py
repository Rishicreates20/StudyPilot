"""SQL for reading a learner's own lessons and recording their study progress.

Lessons are written only by the worker. From the API's side their content is read-only; the one
write is the learner's own progress through a lesson, which the database restricts to that
learner's own lessons and to the lesson's real sections.
"""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.ai.lesson.schema import Lesson, SourceReference
from app.core.db import ReadConnection, UserConnection
from app.retrieval.search import position_text
from app.schemas.lessons import (
    Citation,
    ItemStudy,
    LessonDetail,
    LessonVersion,
    OutlineEntry,
    ProgressState,
    StudyRoadmap,
    TopicInfo,
)

NOT_STARTED = ItemStudy(status="not_started", has_lesson=False, sections_done=0, sections_total=0)

_VERSION_COLUMNS = "id, version, status, title, adjust, is_synthetic, created_at"


@dataclass(frozen=True)
class TopicRecord:
    topic: TopicInfo
    roadmap: StudyRoadmap
    goal_status: str


async def get_topic(connection: UserConnection, user_id: UUID, item_id: UUID) -> TopicRecord | None:
    cursor = await connection.execute(
        """
        select i.id, i.roadmap_id, i.item_key, i.kind, i.title, i.description, i.practice_task,
               i.estimated_minutes, i.day_number, m.title as module_title, r.goal_id, r.version,
               r.status as roadmap_status, r.title as roadmap_title, g.status as goal_status
        from public.roadmap_items i
        join public.roadmaps r on r.id = i.roadmap_id and r.user_id = i.user_id
        join public.learning_goals g on g.id = r.goal_id and g.user_id = r.user_id
        left join public.roadmap_modules m on m.id = i.module_id
        where i.id = %s and i.user_id = %s
        """,
        (item_id, user_id),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    return TopicRecord(
        topic=TopicInfo(
            id=row["id"],
            goal_id=row["goal_id"],
            roadmap_id=row["roadmap_id"],
            key=row["item_key"],
            kind=row["kind"],
            title=row["title"],
            description=row["description"],
            practice_task=row["practice_task"],
            estimated_minutes=row["estimated_minutes"],
            day_number=row["day_number"],
            module_title=row["module_title"],
        ),
        roadmap=StudyRoadmap(
            id=row["roadmap_id"],
            version=row["version"],
            status=row["roadmap_status"],
            title=row["roadmap_title"],
        ),
        goal_status=row["goal_status"],
    )


async def study_by_item(
    connection: ReadConnection, user_id: UUID, roadmap_id: UUID
) -> dict[UUID, ItemStudy]:
    """Each item's study state, for the items of the roadmap that have a lesson."""
    cursor = await connection.execute(
        "select l.item_id, cardinality(l.section_ids) as total, p.status as progress_status,"
        " coalesce(cardinality(p.completed_section_ids), 0) as done"
        " from public.lessons l"
        " left join public.lesson_progress p on p.lesson_id = l.id and p.user_id = l.user_id"
        " where l.roadmap_id = %s and l.user_id = %s order by l.item_id, l.version desc",
        (roadmap_id, user_id),
    )
    versions: dict[UUID, list[dict[str, Any]]] = defaultdict(list)
    for row in await cursor.fetchall():
        versions[row["item_id"]].append(row)

    study: dict[UUID, ItemStudy] = {}
    for item_id, rows in versions.items():
        latest = rows[0]  # newest version first
        statuses = {row["progress_status"] for row in rows}
        if "completed" in statuses:
            study[item_id] = ItemStudy(
                status="completed",
                has_lesson=True,
                sections_done=latest["total"],
                sections_total=latest["total"],
            )
        else:
            study[item_id] = ItemStudy(
                status="in_progress" if statuses - {None} else "not_started",
                has_lesson=True,
                sections_done=latest["done"],
                sections_total=latest["total"],
            )
    return study


async def outline(
    connection: UserConnection, user_id: UUID, roadmap_id: UUID
) -> list[OutlineEntry]:
    """The roadmap's topics and optional extras (not revision sessions) in study order."""
    cursor = await connection.execute(
        "select i.id, i.item_key, i.title, i.kind, i.estimated_minutes, m.title as module_title"
        " from public.roadmap_items i"
        " left join public.roadmap_modules m on m.id = i.module_id"
        " where i.roadmap_id = %s and i.user_id = %s and i.kind <> 'revision'"
        " order by i.position",
        (roadmap_id, user_id),
    )
    study = await study_by_item(connection, user_id, roadmap_id)
    return [
        OutlineEntry(
            item_id=row["id"],
            key=row["item_key"],
            title=row["title"],
            kind=row["kind"],
            module_title=row["module_title"],
            estimated_minutes=row["estimated_minutes"],
            study=study.get(row["id"], NOT_STARTED),
        )
        for row in await cursor.fetchall()
    ]


async def list_versions(
    connection: UserConnection, user_id: UUID, item_id: UUID
) -> list[LessonVersion]:
    """Every version of a topic's lesson, newest first."""
    cursor = await connection.execute(
        f"select {_VERSION_COLUMNS} from public.lessons"  # noqa: S608 - a module constant
        " where item_id = %s and user_id = %s order by version desc",
        (item_id, user_id),
    )
    return [LessonVersion.model_validate(row) for row in await cursor.fetchall()]


async def get_detail(
    connection: ReadConnection, user_id: UUID, item_id: UUID, lesson_id: UUID | None
) -> LessonDetail | None:
    """A topic's lesson with its content: the one asked for, or else the current version."""
    if lesson_id is None:
        cursor = await connection.execute(
            "select * from public.lessons where item_id = %s and user_id = %s"
            " and status = 'current'",
            (item_id, user_id),
        )
    else:
        cursor = await connection.execute(
            "select * from public.lessons where id = %s and item_id = %s and user_id = %s",
            (lesson_id, item_id, user_id),
        )
    row = await cursor.fetchone()
    if row is None:
        return None
    # Re-validated on every read: a stored document that no longer fits the model is an error,
    # not something to render.
    content = Lesson.model_validate(row["content"])
    return LessonDetail(
        id=row["id"],
        version=row["version"],
        status=row["status"],
        title=row["title"],
        adjust=row["adjust"],
        is_synthetic=row["is_synthetic"],
        created_at=row["created_at"],
        item_id=row["item_id"],
        language=row["language"],
        content=content,
        content_version=row["content_version"],
        revision_feedback=row["revision_feedback"],
        based_on_lesson_id=row["based_on_lesson_id"],
        prompt_version=row["prompt_version"],
        provider=row["provider"],
        model_id=row["model_id"],
        citations=await resolve_citations(connection, user_id, content.source_references),
    )


_EXCERPT_CHARS = 400


async def resolve_citations(
    connection: ReadConnection, user_id: UUID, references: Sequence[SourceReference]
) -> list[Citation]:
    """Look up the passages a lesson cites; one that no longer exists is marked unavailable."""
    if not references:
        return []
    wanted: list[UUID] = []
    for reference in references:
        try:
            wanted.append(UUID(reference.chunk_id))
        except ValueError:
            continue  # not an identifier of ours: shown as unavailable below
    found: dict[UUID, dict[str, Any]] = {}
    if wanted:
        cursor = await connection.execute(
            "select c.id, c.document_id, d.title, d.paginated, c.page_start, c.page_end, c.content"
            " from public.document_chunks c"
            " join public.source_documents d on d.id = c.document_id and d.user_id = c.user_id"
            " where c.user_id = %s and c.id = any(%s)",
            (user_id, wanted),
        )
        found = {row["id"]: row for row in await cursor.fetchall()}
    citations: list[Citation] = []
    for reference in references:
        try:
            row = found.get(UUID(reference.chunk_id))
        except ValueError:
            row = None
        if row is None:
            citations.append(
                Citation(
                    source_id=reference.source_id,
                    chunk_id=reference.chunk_id,
                    note=reference.note,
                    available=False,
                )
            )
            continue
        content: str = row["content"]
        citations.append(
            Citation(
                source_id=reference.source_id,
                chunk_id=reference.chunk_id,
                note=reference.note,
                available=True,
                document_id=row["document_id"],
                document_title=row["title"],
                position=position_text(
                    paginated=row["paginated"],
                    page_start=row["page_start"],
                    page_end=row["page_end"],
                ),
                page_start=row["page_start"],
                excerpt=(
                    content
                    if len(content) <= _EXCERPT_CHARS
                    else content[:_EXCERPT_CHARS].rsplit(" ", 1)[0] + " ..."
                ),
            )
        )
    return citations


async def get_current_id(connection: UserConnection, user_id: UUID, item_id: UUID) -> UUID | None:
    cursor = await connection.execute(
        "select id from public.lessons where item_id = %s and user_id = %s and status = 'current'",
        (item_id, user_id),
    )
    row = await cursor.fetchone()
    return row["id"] if row else None


@dataclass(frozen=True)
class LessonRef:
    """What saving progress (and exporting) needs to know about a lesson."""

    id: UUID
    item_id: UUID
    section_ids: list[str]
    goal_id: UUID
    goal_status: str


async def get_ref(connection: UserConnection, user_id: UUID, lesson_id: UUID) -> LessonRef | None:
    cursor = await connection.execute(
        "select l.id, l.item_id, l.section_ids, g.id as goal_id, g.status as goal_status"
        " from public.lessons l"
        " join public.roadmaps r on r.id = l.roadmap_id and r.user_id = l.user_id"
        " join public.learning_goals g on g.id = r.goal_id and g.user_id = r.user_id"
        " where l.id = %s and l.user_id = %s",
        (lesson_id, user_id),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    return LessonRef(
        id=row["id"],
        item_id=row["item_id"],
        section_ids=list(row["section_ids"]),
        goal_id=row["goal_id"],
        goal_status=row["goal_status"],
    )


_PROGRESS_COLUMNS = (
    "lesson_id, status, completed_section_ids, current_section_id, started_at, last_studied_at,"
    " completed_at"
)


async def get_progress(
    connection: UserConnection, user_id: UUID, lesson_id: UUID
) -> ProgressState | None:
    cursor = await connection.execute(
        f"select {_PROGRESS_COLUMNS} from public.lesson_progress"  # noqa: S608
        " where lesson_id = %s and user_id = %s",
        (lesson_id, user_id),
    )
    row = await cursor.fetchone()
    return ProgressState.model_validate(row) if row else None


async def save_progress(
    connection: UserConnection,
    user_id: UUID,
    lesson_id: UUID,
    *,
    completed_section_ids: list[str],
    current_section_id: str | None,
    completed: bool,
) -> ProgressState:
    """Replace the learner's saved place in a lesson (or create it on the first save).

    Finishing keeps the original completion time if the lesson was already finished; un-finishing
    clears it. The database checks the section ids and refuses a "completed" lesson with sections
    left, whatever this function is told.
    """
    cursor = await connection.execute(
        "insert into public.lesson_progress"  # noqa: S608 - the f-string below is a constant
        " (lesson_id, user_id, status, completed_section_ids, current_section_id, completed_at)"
        " values (%(lesson)s, %(user)s, %(status)s, %(done)s, %(current)s,"
        "         case when %(completed)s then now() end)"
        " on conflict (lesson_id) do update set"
        "  status = excluded.status,"
        "  completed_section_ids = excluded.completed_section_ids,"
        "  current_section_id = excluded.current_section_id,"
        "  completed_at = case when %(completed)s"
        "                      then coalesce(public.lesson_progress.completed_at, now()) end"
        f" returning {_PROGRESS_COLUMNS}",
        {
            "lesson": lesson_id,
            "user": user_id,
            "status": "completed" if completed else "in_progress",
            "done": completed_section_ids,
            "current": current_section_id,
            "completed": completed,
        },
    )
    row = await cursor.fetchone()
    if row is None:
        raise RuntimeError("progress upsert returned no row")
    return ProgressState.model_validate(row)
