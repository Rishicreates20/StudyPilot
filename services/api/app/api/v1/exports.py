from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request, Response

from app.api.deps import DatabaseDep, ExportFilesDep
from app.core.errors import ProblemDetail
from app.core.security import AccessToken, CurrentPrincipal
from app.schemas.exports import (
    DownloadLink,
    Export,
    ExportList,
    LessonExportRequest,
    RoadmapExportRequest,
)
from app.services import exports as exports_service

router = APIRouter(tags=["exports"])

_NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {"model": ProblemDetail, "description": "No such lesson, roadmap, goal or export"}
}
_CONFLICT: dict[int | str, dict[str, Any]] = {
    409: {"model": ProblemDetail, "description": "The request conflicts with the current state"}
}
_STORAGE: dict[int | str, dict[str, Any]] = {
    503: {"model": ProblemDetail, "description": "File storage is unavailable or not set up"}
}
_REQUESTED: dict[int | str, dict[str, Any]] = {
    200: {"model": Export, "description": "The export already exists: ready, or being made"},
    429: {"model": ProblemDetail, "description": "Today's export allowance is used up"},
}


@router.post(
    "/lessons/{lesson_id}/exports",
    response_model=Export,
    status_code=202,
    summary="Export a lesson as PDF notes, a PDF revision sheet or PowerPoint slides",
    responses={**_NOT_FOUND, **_CONFLICT, **_STORAGE, **_REQUESTED},
)
async def export_lesson(
    lesson_id: UUID,
    payload: LessonExportRequest,
    request: Request,
    response: Response,
    principal: CurrentPrincipal,
    token: AccessToken,
    database: DatabaseDep,
    files: ExportFilesDep,
) -> Export:
    """Queues a background job and returns the export at once (202); follow `GET /v1/exports/{id}`.
    Asking again for the same lesson and format returns the same export (200) without a new job,
    unless the last attempt failed."""
    export, queued = await exports_service.request_lesson_export(
        database,
        principal,
        token,
        files=files,
        settings=request.app.state.settings,
        lesson_id=lesson_id,
        export_format=payload.format,
    )
    if not queued:
        response.status_code = 200
    return export


@router.post(
    "/roadmaps/{roadmap_id}/exports",
    response_model=Export,
    status_code=202,
    summary="Export a roadmap version as a PDF plan or PowerPoint slides",
    responses={**_NOT_FOUND, **_CONFLICT, **_STORAGE, **_REQUESTED},
)
async def export_roadmap(
    roadmap_id: UUID,
    payload: RoadmapExportRequest,
    request: Request,
    response: Response,
    principal: CurrentPrincipal,
    token: AccessToken,
    database: DatabaseDep,
    files: ExportFilesDep,
) -> Export:
    export, queued = await exports_service.request_roadmap_export(
        database,
        principal,
        token,
        files=files,
        settings=request.app.state.settings,
        roadmap_id=roadmap_id,
        export_format=payload.format,
    )
    if not queued:
        response.status_code = 200
    return export


@router.get(
    "/goals/{goal_id}/exports",
    response_model=ExportList,
    summary="A goal's exported files, newest first, each with its status",
    responses=_NOT_FOUND,
)
async def list_exports(
    goal_id: UUID, principal: CurrentPrincipal, database: DatabaseDep
) -> ExportList:
    async with database.user_transaction(principal) as connection:
        return await exports_service.list_exports(connection, principal, goal_id)


@router.get(
    "/exports/{export_id}",
    response_model=Export,
    summary="One export with its status and newest job",
    responses=_NOT_FOUND,
)
async def get_export(export_id: UUID, principal: CurrentPrincipal, database: DatabaseDep) -> Export:
    async with database.user_transaction(principal) as connection:
        return await exports_service.get_export(connection, principal, export_id)


@router.post(
    "/exports/{export_id}/download-link",
    response_model=DownloadLink,
    summary="A short-lived signed link to download a ready export",
    responses={**_NOT_FOUND, **_CONFLICT, **_STORAGE},
)
async def create_download_link(
    export_id: UUID,
    request: Request,
    principal: CurrentPrincipal,
    token: AccessToken,
    database: DatabaseDep,
    files: ExportFilesDep,
) -> DownloadLink:
    """The link works for a couple of minutes and only for this one file. A POST, so it is never
    cached or prefetched. `url` is null on servers that keep files on their own disk; use
    `GET /v1/exports/{id}/file` there."""
    return await exports_service.download_link(
        database,
        principal,
        token,
        files=files,
        settings=request.app.state.settings,
        export_id=export_id,
    )


@router.get(
    "/exports/{export_id}/file",
    summary="Download a ready export through the API",
    response_class=Response,
    responses={
        200: {
            "description": "The file, as an attachment",
            "content": {
                "application/pdf": {},
                "application/vnd.openxmlformats-officedocument.presentationml.presentation": {},
            },
        },
        **_NOT_FOUND,
        **_CONFLICT,
        **_STORAGE,
    },
)
async def download_file(
    export_id: UUID,
    principal: CurrentPrincipal,
    token: AccessToken,
    database: DatabaseDep,
    files: ExportFilesDep,
) -> Response:
    """Always an attachment, never displayed in the browser."""
    data, content_type, file_name = await exports_service.read_file(
        database, principal, token, files=files, export_id=export_id
    )
    return Response(
        content=data,
        media_type=content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{file_name}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


@router.delete(
    "/exports/{export_id}",
    status_code=204,
    summary="Delete an export and its file",
    responses={**_NOT_FOUND, **_CONFLICT, **_STORAGE},
)
async def delete_export(
    export_id: UUID,
    principal: CurrentPrincipal,
    token: AccessToken,
    database: DatabaseDep,
    files: ExportFilesDep,
) -> Response:
    await exports_service.delete_export(
        database, principal, token, files=files, export_id=export_id
    )
    return Response(status_code=204)
