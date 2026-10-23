"""The worker's reads and writes for export jobs. Every query filters on the job's ``user_id``.

The lesson and roadmap are read through the same repository functions the API uses
(``lessons.get_detail``, ``roadmaps.get_detail``), so an export shows exactly what the learner
sees, citations resolved the same way. ``save_file`` is the only place an export becomes ready; it
runs in the transaction that completes the job.
"""

import hashlib
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.core.db import SystemConnection
from app.exports.model import ExportFormat, LessonSource, RenderedFile, RoadmapSource
from app.repositories import lessons as lessons_repo
from app.repositories import roadmaps as roadmaps_repo


@dataclass(frozen=True)
class ExportTask:
    id: UUID
    goal_id: UUID
    lesson_id: UUID | None
    roadmap_id: UUID | None
    format: ExportFormat
    # The upload capability the API made with the learner's token; None if it was never given.
    upload_token: str | None
    ready_at: datetime | None
    goal_title: str


async def load_task(
    connection: SystemConnection, user_id: UUID, export_id: UUID
) -> ExportTask | None:
    cursor = await connection.execute(
        "select e.id, e.goal_id, e.lesson_id, e.roadmap_id, e.format, e.upload_token, e.ready_at,"
        " g.title as goal_title"
        " from public.exports e"
        " join public.learning_goals g on g.id = e.goal_id and g.user_id = e.user_id"
        " where e.id = %s and e.user_id = %s",
        (export_id, user_id),
    )
    row = await cursor.fetchone()
    return ExportTask(**row) if row else None


async def lesson_source(
    connection: SystemConnection, user_id: UUID, lesson_id: UUID, goal_title: str
) -> LessonSource | None:
    cursor = await connection.execute(
        "select l.item_id, i.title as topic_title from public.lessons l"
        " join public.roadmap_items i on i.id = l.item_id and i.user_id = l.user_id"
        " where l.id = %s and l.user_id = %s",
        (lesson_id, user_id),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    detail = await lessons_repo.get_detail(connection, user_id, row["item_id"], lesson_id)
    if detail is None:
        return None
    return LessonSource(lesson=detail, topic_title=row["topic_title"], goal_title=goal_title)


async def roadmap_source(
    connection: SystemConnection, user_id: UUID, roadmap_id: UUID, goal_title: str
) -> RoadmapSource | None:
    roadmap = await roadmaps_repo.get_detail(connection, user_id, roadmap_id)
    return RoadmapSource(roadmap=roadmap, goal_title=goal_title) if roadmap else None


async def save_file(
    connection: SystemConnection,
    user_id: UUID,
    export_id: UUID,
    *,
    storage_path: str,
    rendered: RenderedFile,
) -> bool:
    """Record the stored file and mark the export ready (once); the upload capability goes."""
    cursor = await connection.execute(
        "update public.exports set storage_path = %s, file_name = %s, content_type = %s,"
        " size_bytes = %s, sha256 = %s, page_count = %s, unsupported_characters = %s,"
        " ready_at = now(), upload_token = null"
        " where id = %s and user_id = %s and ready_at is null",
        (
            storage_path,
            rendered.file_name,
            rendered.content_type,
            len(rendered.data),
            hashlib.sha256(rendered.data).hexdigest(),
            max(1, rendered.page_count),
            rendered.unsupported_characters,
            export_id,
            user_id,
        ),
    )
    return cursor.rowcount == 1


async def clear_grant(connection: SystemConnection, user_id: UUID, export_id: UUID) -> None:
    """Drop the upload capability of an export whose job has ended without a file."""
    await connection.execute(
        "update public.exports set upload_token = null"
        " where id = %s and user_id = %s and ready_at is null",
        (export_id, user_id),
    )
