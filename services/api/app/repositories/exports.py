"""SQL for a learner's own exports. Data access only; the rules live in the service.

A learner may create an export of their own lesson or roadmap version (the database sets its goal
from the source), give it the upload capability for the worker while it is not ready, read it and
delete it. Whether it is ready, where its file is and what it weighs are written only by the worker:
the column grants forbid anything else. ``upload_token`` is never selected here: learners have no
privilege to read it back.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.core.db import UserConnection
from app.exports.model import ExportFormat

_COLUMNS = (
    "e.id, e.goal_id, e.lesson_id, e.roadmap_id, e.format, e.template_version, e.storage_path,"
    " e.file_name, e.content_type, e.size_bytes, e.page_count, e.unsupported_characters,"
    " e.ready_at, e.created_at, coalesce(l.title, r.title, '') as source_title,"
    " coalesce(l.version, r.version, 0) as source_version"
)
# The source's title and version, for showing which lesson or roadmap a file was made from.
_FROM = (
    " from public.exports e"
    " left join public.lessons l on l.id = e.lesson_id and l.user_id = e.user_id"
    " left join public.roadmaps r on r.id = e.roadmap_id and r.user_id = e.user_id"
)


@dataclass(frozen=True)
class ExportRow:
    id: UUID
    goal_id: UUID
    lesson_id: UUID | None
    roadmap_id: UUID | None
    format: ExportFormat
    template_version: str
    storage_path: str | None
    file_name: str | None
    content_type: str | None
    size_bytes: int | None
    page_count: int | None
    unsupported_characters: int | None
    ready_at: datetime | None
    created_at: datetime
    source_title: str
    source_version: int


def _row(row: dict[str, object]) -> ExportRow:
    return ExportRow(**row)  # type: ignore[arg-type]


async def find_for_source(
    connection: UserConnection,
    user_id: UUID,
    *,
    lesson_id: UUID | None,
    roadmap_id: UUID | None,
    export_format: ExportFormat,
    template_version: str,
) -> ExportRow | None:
    """The one export of this source, format and template version, if it exists."""
    cursor = await connection.execute(
        f"select {_COLUMNS}{_FROM}"  # noqa: S608 - module constants
        " where e.user_id = %(user)s and e.format = %(format)s"
        " and e.template_version = %(template)s"
        " and e.lesson_id is not distinct from %(lesson)s"
        " and e.roadmap_id is not distinct from %(roadmap)s",
        {
            "user": user_id,
            "format": export_format,
            "template": template_version,
            "lesson": lesson_id,
            "roadmap": roadmap_id,
        },
    )
    row = await cursor.fetchone()
    return _row(row) if row else None


async def insert(
    connection: UserConnection,
    user_id: UUID,
    *,
    lesson_id: UUID | None,
    roadmap_id: UUID | None,
    export_format: ExportFormat,
    template_version: str,
) -> ExportRow:
    """Create the export, or find the one a concurrent request created first."""
    values = (user_id, lesson_id, roadmap_id, export_format, template_version)
    if lesson_id is not None:
        await connection.execute(
            "insert into public.exports (user_id, lesson_id, roadmap_id, format, template_version)"
            " values (%s, %s, %s, %s, %s) on conflict (lesson_id, format, template_version)"
            " where lesson_id is not null do nothing",
            values,
        )
    else:
        await connection.execute(
            "insert into public.exports (user_id, lesson_id, roadmap_id, format, template_version)"
            " values (%s, %s, %s, %s, %s) on conflict (roadmap_id, format, template_version)"
            " where roadmap_id is not null do nothing",
            values,
        )
    found = await find_for_source(
        connection,
        user_id,
        lesson_id=lesson_id,
        roadmap_id=roadmap_id,
        export_format=export_format,
        template_version=template_version,
    )
    if found is None:
        raise RuntimeError("the new export could not be read back")
    return found


async def get(
    connection: UserConnection, user_id: UUID, export_id: UUID, *, for_update: bool = False
) -> ExportRow | None:
    lock = " for update of e" if for_update else ""
    cursor = await connection.execute(
        f"select {_COLUMNS}{_FROM} where e.id = %s and e.user_id = %s{lock}",  # noqa: S608
        (export_id, user_id),
    )
    row = await cursor.fetchone()
    return _row(row) if row else None


async def list_for_goal(
    connection: UserConnection, user_id: UUID, goal_id: UUID
) -> list[ExportRow]:
    cursor = await connection.execute(
        f"select {_COLUMNS}{_FROM}"  # noqa: S608
        " where e.user_id = %s and e.goal_id = %s order by e.created_at desc, e.id desc",
        (user_id, goal_id),
    )
    return [_row(row) for row in await cursor.fetchall()]


async def set_upload_grant(
    connection: UserConnection, user_id: UUID, export_id: UUID, grant: str
) -> bool:
    """Give the worker a fresh upload capability. Refused by the database once a file is ready."""
    cursor = await connection.execute(
        "update public.exports set upload_token = %s"
        " where id = %s and user_id = %s and ready_at is null",
        (grant, export_id, user_id),
    )
    return cursor.rowcount == 1


async def delete(connection: UserConnection, user_id: UUID, export_id: UUID) -> bool:
    cursor = await connection.execute(
        "delete from public.exports where id = %s and user_id = %s", (export_id, user_id)
    )
    return cursor.rowcount == 1


async def storage_paths_for_goal(
    connection: UserConnection, user_id: UUID, goal_id: UUID
) -> list[str]:
    """The stored files of a goal's exports, for removing them when the goal is deleted."""
    cursor = await connection.execute(
        "select storage_path from public.exports"
        " where user_id = %s and goal_id = %s and storage_path is not null",
        (user_id, goal_id),
    )
    return [row["storage_path"] for row in await cursor.fetchall()]
