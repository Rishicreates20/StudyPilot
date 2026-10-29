"""Business rules for exported files: asking for one, following it, downloading it, deleting it.

The API never renders a file: asking for an export validates the request, gives the worker a
one-object upload capability (made with the learner's own token) and queues an ``export`` job.
Asking again is cheap and safe: a ready export is returned as it is, one being made returns its
running job, and only a failed (or never started) export gets a new job. The database backs this up
with one export per source, format and template version, and one active job per export.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import psycopg.errors
import structlog

from app.core.config import Settings
from app.core.db import Database, UserConnection
from app.core.errors import (
    ConflictError,
    NotFoundError,
    RateLimitedError,
    ServiceUnavailableError,
)
from app.core.security import Principal
from app.documents.storage import StorageError
from app.exports.files import ExportFiles, object_path
from app.exports.model import TEMPLATE_VERSION, ExportFormat
from app.repositories import exports as exports_repo
from app.repositories import goals as goals_repo
from app.repositories import jobs as jobs_repo
from app.repositories import lessons as lessons_repo
from app.repositories import roadmaps as roadmaps_repo
from app.repositories.exports import ExportRow
from app.schemas.exports import DownloadLink, Export, ExportList, ExportStatus
from app.schemas.jobs import GenerationJob
from app.services.documents import storage_error

log = structlog.get_logger("app.exports")

_ALLOWANCE_WINDOW = timedelta(hours=24)
_ACTIVE = ("queued", "running")


def _export_not_found() -> NotFoundError:
    return NotFoundError("Export not found.", code="EXPORT_NOT_FOUND")


def _archived() -> ConflictError:
    return ConflictError(
        "This goal is archived. Restore it to export its lessons and roadmaps.",
        code="GOAL_ARCHIVED",
    )


def _require_files(files: ExportFiles | None) -> ExportFiles:
    if files is None:
        raise ServiceUnavailableError(
            "File storage isn't set up on this server yet, so files can't be exported.",
            code="STORAGE_NOT_CONFIGURED",
        )
    return files


def _status(row: ExportRow, job: GenerationJob | None) -> ExportStatus:
    if row.ready_at is not None:
        return "ready"
    if job is None:
        return "not_started"
    if job.status in _ACTIVE:
        return "processing"
    return "failed"


def _to_schema(row: ExportRow, job: GenerationJob | None) -> Export:
    return Export(
        id=row.id,
        goal_id=row.goal_id,
        lesson_id=row.lesson_id,
        roadmap_id=row.roadmap_id,
        source_title=row.source_title,
        source_version=row.source_version,
        format=row.format,
        template_version=row.template_version,
        status=_status(row, job),
        file_name=row.file_name,
        content_type=row.content_type,
        size_bytes=row.size_bytes,
        page_count=row.page_count,
        unsupported_characters=row.unsupported_characters,
        ready_at=row.ready_at,
        created_at=row.created_at,
        job=job,
    )


# --- Asking for an export ----------------------------------------------------------------------


async def request_lesson_export(
    database: Database,
    principal: Principal,
    token: str,
    *,
    files: ExportFiles | None,
    settings: Settings,
    lesson_id: UUID,
    export_format: ExportFormat,
) -> tuple[Export, bool]:
    """The export (and whether a new job was queued for it) of one of the learner's lessons."""
    async with database.user_transaction(principal) as connection:
        ref = await lessons_repo.get_ref(connection, principal.user_id, lesson_id)
        if ref is None:
            raise NotFoundError("Lesson not found.", code="LESSON_NOT_FOUND")
        if ref.goal_status == "archived":
            raise _archived()
    return await _request(
        database,
        principal,
        token,
        files=files,
        settings=settings,
        goal_id=ref.goal_id,
        lesson_id=lesson_id,
        roadmap_id=None,
        export_format=export_format,
    )


async def request_roadmap_export(
    database: Database,
    principal: Principal,
    token: str,
    *,
    files: ExportFiles | None,
    settings: Settings,
    roadmap_id: UUID,
    export_format: ExportFormat,
) -> tuple[Export, bool]:
    """The export (and whether a new job was queued for it) of one of the learner's roadmaps."""
    async with database.user_transaction(principal) as connection:
        summary = await roadmaps_repo.get_summary(connection, principal.user_id, roadmap_id)
        if summary is None:
            raise NotFoundError("Roadmap not found.", code="ROADMAP_NOT_FOUND")
        goal = await goals_repo.get(connection, principal.user_id, summary.goal_id)
        if goal is None:
            raise NotFoundError("Roadmap not found.", code="ROADMAP_NOT_FOUND")
        if goal.status == "archived":
            raise _archived()
    return await _request(
        database,
        principal,
        token,
        files=files,
        settings=settings,
        goal_id=summary.goal_id,
        lesson_id=None,
        roadmap_id=roadmap_id,
        export_format=export_format,
    )


async def _lock_open_goal(
    connection: UserConnection, user_id: UUID, goal_id: UUID, *, lesson: bool
) -> None:
    """Lock the goal until the transaction ends and refuse an archived one, as lessons and quizzes
    do: a goal archived while an export is being asked for cannot still get a job."""
    goal = await goals_repo.get(connection, user_id, goal_id, for_update=True)
    if goal is None:
        if lesson:
            raise NotFoundError("Lesson not found.", code="LESSON_NOT_FOUND")
        raise NotFoundError("Roadmap not found.", code="ROADMAP_NOT_FOUND")
    if goal.status == "archived":
        raise _archived()


async def _check_allowance(connection: UserConnection, user_id: UUID, settings: Settings) -> None:
    since = datetime.now(UTC) - _ALLOWANCE_WINDOW
    used = await jobs_repo.count_since(connection, user_id, since, job_type="export")
    if used >= settings.export_jobs_per_user_per_day:
        raise RateLimitedError(
            f"You can make up to {settings.export_jobs_per_user_per_day} exports a day. "
            "Please try again tomorrow.",
            code="EXPORT_ALLOWANCE_USED",
        )


async def _request(
    database: Database,
    principal: Principal,
    token: str,
    *,
    files: ExportFiles | None,
    settings: Settings,
    goal_id: UUID,
    lesson_id: UUID | None,
    roadmap_id: UUID | None,
    export_format: ExportFormat,
) -> tuple[Export, bool]:
    user_id = principal.user_id
    lesson = lesson_id is not None
    # 1. Find or create the export; a ready or busy one is returned as it is.
    async with database.user_transaction(principal) as connection:
        await _lock_open_goal(connection, user_id, goal_id, lesson=lesson)
        row = await exports_repo.find_for_source(
            connection,
            user_id,
            lesson_id=lesson_id,
            roadmap_id=roadmap_id,
            export_format=export_format,
            template_version=TEMPLATE_VERSION,
        )
        if row is not None:
            job = await jobs_repo.latest_for_export(connection, user_id, row.id)
            if row.ready_at is not None or (job is not None and job.status in _ACTIVE):
                return _to_schema(row, job), False
        store = _require_files(files)
        await _check_allowance(connection, user_id, settings)
        if row is None:
            row = await exports_repo.insert(
                connection,
                user_id,
                lesson_id=lesson_id,
                roadmap_id=roadmap_id,
                export_format=export_format,
                template_version=TEMPLATE_VERSION,
            )

    # 2. A one-object upload capability for the worker, made with the learner's token (outside
    #    any transaction: it is a network call).
    try:
        grant = await store.grant_upload(object_path(user_id, row.id, row.format), token=token)
    except StorageError as problem:
        raise storage_error(problem) from None

    # 3. Hand it over and queue the job. A concurrent request that queued one first wins. The goal
    #    is locked and checked again: it may have been archived, or the allowance used up by
    #    another request, while the link was being made.
    try:
        async with database.user_transaction(principal) as connection:
            await _lock_open_goal(connection, user_id, goal_id, lesson=lesson)
            await _check_allowance(connection, user_id, settings)
            if not await exports_repo.set_upload_grant(connection, user_id, row.id, grant):
                # It became ready in the meantime (another request's job finished).
                fresh = await exports_repo.get(connection, user_id, row.id)
                if fresh is None:
                    raise _export_not_found()
                job = await jobs_repo.latest_for_export(connection, user_id, row.id)
                return _to_schema(fresh, job), False
            job = await jobs_repo.insert(
                connection,
                user_id,
                row.goal_id,
                idempotency_key=None,
                request={"format": row.format, "template_version": row.template_version},
                job_type="export",
                export_id=row.id,
            )
    except psycopg.errors.UniqueViolation:
        async with database.user_transaction(principal) as connection:
            fresh = await exports_repo.get(connection, user_id, row.id)
            if fresh is None:
                raise _export_not_found() from None
            job = await jobs_repo.latest_for_export(connection, user_id, row.id)
            return _to_schema(fresh, job), False
    log.info("export.queued", export_id=str(row.id), job_id=str(job.id), format=row.format)
    return _to_schema(row, job), True


# --- Reading -------------------------------------------------------------------------------------


async def get_export(connection: UserConnection, principal: Principal, export_id: UUID) -> Export:
    row = await exports_repo.get(connection, principal.user_id, export_id)
    if row is None:
        raise _export_not_found()
    job = await jobs_repo.latest_for_export(connection, principal.user_id, export_id)
    return _to_schema(row, job)


async def list_exports(
    connection: UserConnection, principal: Principal, goal_id: UUID
) -> ExportList:
    if await goals_repo.get(connection, principal.user_id, goal_id) is None:
        raise NotFoundError("Goal not found.", code="GOAL_NOT_FOUND")
    rows = await exports_repo.list_for_goal(connection, principal.user_id, goal_id)
    jobs = await jobs_repo.latest_per_export(connection, principal.user_id, goal_id)
    return ExportList(items=[_to_schema(row, jobs.get(row.id)) for row in rows])


@dataclass(frozen=True)
class _ReadyFile:
    storage_path: str
    file_name: str
    content_type: str


async def _ready(database: Database, principal: Principal, export_id: UUID) -> _ReadyFile:
    async with database.user_transaction(principal) as connection:
        row = await exports_repo.get(connection, principal.user_id, export_id)
    if row is None:
        raise _export_not_found()
    if row.ready_at is None or row.storage_path is None or row.file_name is None:
        raise ConflictError("This export isn't ready yet.", code="EXPORT_NOT_READY")
    return _ReadyFile(
        storage_path=row.storage_path,
        file_name=row.file_name,
        content_type=row.content_type or "application/octet-stream",
    )


async def download_link(
    database: Database,
    principal: Principal,
    token: str,
    *,
    files: ExportFiles | None,
    settings: Settings,
    export_id: UUID,
) -> DownloadLink:
    """A short-lived signed link to the learner's own file, minted with their own token."""
    ready = await _ready(database, principal, export_id)
    store = _require_files(files)
    try:
        url = await store.download_link(ready.storage_path, token=token, file_name=ready.file_name)
    except StorageError as problem:
        raise storage_error(problem) from None
    expires = (
        datetime.now(UTC) + timedelta(seconds=settings.export_download_seconds) if url else None
    )
    log.info("export.link_issued", export_id=str(export_id), signed=url is not None)
    return DownloadLink(url=url, expires_at=expires, file_name=ready.file_name)


async def read_file(
    database: Database,
    principal: Principal,
    token: str,
    *,
    files: ExportFiles | None,
    export_id: UUID,
) -> tuple[bytes, str, str]:
    """The file's bytes, type and download name, read with the learner's own token."""
    ready = await _ready(database, principal, export_id)
    store = _require_files(files)
    try:
        data = await store.get(ready.storage_path, token=token)
    except StorageError as problem:
        raise storage_error(problem) from None
    return data, ready.content_type, ready.file_name


# --- Deleting ----------------------------------------------------------------------------------


async def delete_export(
    database: Database,
    principal: Principal,
    token: str,
    *,
    files: ExportFiles | None,
    export_id: UUID,
) -> None:
    """Remove the file, then the export (its jobs cascade). Not while a job is making it."""
    async with database.user_transaction(principal) as connection:
        row = await exports_repo.get(connection, principal.user_id, export_id)
        if row is None:
            raise _export_not_found()
        job = await jobs_repo.latest_for_export(connection, principal.user_id, export_id)
        if job is not None and job.status in _ACTIVE:
            raise ConflictError(
                "This file is still being made. Wait for it to finish, then delete it.",
                code="EXPORT_BUSY",
            )
    if row.storage_path is not None:
        store = _require_files(files)
        try:
            await store.delete(row.storage_path, token=token)
        except StorageError as problem:
            raise storage_error(problem) from None
    async with database.user_transaction(principal) as connection:
        await exports_repo.delete(connection, principal.user_id, export_id)
    log.info("export.deleted", export_id=str(export_id))


async def purge_goal_exports(
    database: Database,
    principal: Principal,
    token: str,
    *,
    files: ExportFiles | None,
    goal_id: UUID,
) -> None:
    """Delete the stored export files of a goal that is about to be deleted (the rows cascade).

    Runs before ``documents.purge_goal_files`` (exported files can be made again, uploaded ones
    cannot), so it makes the same checks: only an archived goal of the caller's, and nothing is
    removed for any other goal.
    """
    async with database.user_transaction(principal) as connection:
        goal = await goals_repo.get(connection, principal.user_id, goal_id)
        if goal is None:
            raise NotFoundError("Goal not found.", code="GOAL_NOT_FOUND")
        if goal.status != "archived":
            raise ConflictError(
                "Archive this goal before deleting it permanently.", code="GOAL_NOT_ARCHIVED"
            )
        paths = await exports_repo.storage_paths_for_goal(connection, principal.user_id, goal_id)
    if not paths:
        return
    store = _require_files(files)
    for path in paths:
        try:
            await store.delete(path, token=token)
        except StorageError as problem:
            raise storage_error(problem) from None
    log.info("export.goal_files_purged", goal_id=str(goal_id), files=len(paths))
