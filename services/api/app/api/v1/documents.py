from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response

from app.api.deps import DatabaseDep, FilesDep, ProviderDep, SearchLimiterDep
from app.core.errors import PayloadTooLargeError, ProblemDetail
from app.core.security import AccessToken, CurrentPrincipal
from app.schemas.documents import (
    Document,
    DocumentList,
    DocumentPage,
    DocumentPages,
    DocumentRename,
    PageEdit,
    PastedMaterial,
    SearchRequest,
    SearchResult,
)
from app.services import documents as documents_service

router = APIRouter(tags=["documents"])

_NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {"model": ProblemDetail, "description": "No such goal, document or page for this user"}
}
_CONFLICT: dict[int | str, dict[str, Any]] = {
    409: {"model": ProblemDetail, "description": "The request conflicts with the current state"}
}
_STORAGE: dict[int | str, dict[str, Any]] = {
    503: {"model": ProblemDetail, "description": "File storage or the AI service is unavailable"}
}


async def _read_body(request: Request, limit: int) -> bytes:
    """The request body, refusing to read more than ``limit`` bytes."""
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > limit:
        raise PayloadTooLargeError(
            "That file is larger than the limit. Upload it in parts.", code="FILE_TOO_LARGE"
        )
    received = bytearray()
    async for chunk in request.stream():
        received += chunk
        if len(received) > limit:
            raise PayloadTooLargeError(
                "That file is larger than the limit. Upload it in parts.", code="FILE_TOO_LARGE"
            )
    return bytes(received)


@router.get(
    "/goals/{goal_id}/documents",
    response_model=DocumentList,
    summary="List a goal's study documents, with what can be done here",
    responses=_NOT_FOUND,
)
async def list_documents(
    goal_id: UUID,
    request: Request,
    principal: CurrentPrincipal,
    database: DatabaseDep,
    files: FilesDep,
) -> DocumentList:
    async with database.user_transaction(principal) as connection:
        return await documents_service.list_documents(
            connection, principal, goal_id, settings=request.app.state.settings, files=files
        )


@router.post(
    "/goals/{goal_id}/documents",
    response_model=Document,
    status_code=202,
    summary="Upload a PDF, a text file or a picture of notes",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
            },
        }
    },
    responses={
        **_NOT_FOUND,
        **_CONFLICT,
        **_STORAGE,
        413: {"model": ProblemDetail, "description": "The file is larger than the limit"},
        415: {"model": ProblemDetail, "description": "The file's content is not a supported type"},
        422: {"model": ProblemDetail, "description": "The file is empty"},
        429: {"model": ProblemDetail, "description": "Today's processing allowance is used up"},
    },
)
async def upload_document(
    goal_id: UUID,
    request: Request,
    principal: CurrentPrincipal,
    token: AccessToken,
    database: DatabaseDep,
    files: FilesDep,
    name: Annotated[str, Query(min_length=1, max_length=300, description="The file's name.")],
    title: Annotated[str | None, Query(max_length=200, description="A title to show.")] = None,
) -> Document:
    """The raw file is the request body. What the file *is* is decided from its bytes, never from
    its name or `Content-Type`. Processing runs in the background: poll the returned `job`."""
    settings = request.app.state.settings
    data = await _read_body(request, settings.document_max_bytes)
    return await documents_service.add_document(
        database,
        principal,
        token,
        files=files,
        settings=settings,
        goal_id=goal_id,
        data=data,
        filename=name,
        title=title,
        pasted=False,
    )


@router.post(
    "/goals/{goal_id}/documents/paste",
    response_model=Document,
    status_code=202,
    summary="Add pasted study material",
    responses={
        **_NOT_FOUND,
        **_CONFLICT,
        **_STORAGE,
        413: {"model": ProblemDetail},
        429: {"model": ProblemDetail},
    },
)
async def paste_material(
    goal_id: UUID,
    payload: PastedMaterial,
    request: Request,
    principal: CurrentPrincipal,
    token: AccessToken,
    database: DatabaseDep,
    files: FilesDep,
) -> Document:
    return await documents_service.add_document(
        database,
        principal,
        token,
        files=files,
        settings=request.app.state.settings,
        goal_id=goal_id,
        data=payload.text.encode("utf-8"),
        filename="pasted-text.txt",
        title=payload.title,
        pasted=True,
    )


@router.post(
    "/goals/{goal_id}/documents/search",
    response_model=SearchResult,
    summary="Find the passages of this goal's documents that answer a question",
    responses={
        **_NOT_FOUND,
        **_STORAGE,
        429: {"model": ProblemDetail, "description": "Searching too quickly"},
    },
)
async def search_documents(
    goal_id: UUID,
    payload: SearchRequest,
    request: Request,
    principal: CurrentPrincipal,
    database: DatabaseDep,
    provider: ProviderDep,
    limiter: SearchLimiterDep,
) -> SearchResult:
    """Only the caller's own ready documents are searched. `enough_evidence: false` means nothing
    matched well enough: the material doesn't cover the question."""
    return await documents_service.search(
        database,
        principal,
        provider=provider,
        limiter=limiter,
        settings=request.app.state.settings,
        goal_id=goal_id,
        payload=payload,
    )


@router.get(
    "/documents/{document_id}",
    response_model=Document,
    summary="One document, with its latest processing job",
    responses=_NOT_FOUND,
)
async def get_document(
    document_id: UUID, principal: CurrentPrincipal, database: DatabaseDep
) -> Document:
    async with database.user_transaction(principal) as connection:
        return await documents_service.get_document(connection, principal, document_id)


@router.patch(
    "/documents/{document_id}",
    response_model=Document,
    summary="Rename a document",
    responses={**_NOT_FOUND, **_CONFLICT},
)
async def rename_document(
    document_id: UUID, payload: DocumentRename, principal: CurrentPrincipal, database: DatabaseDep
) -> Document:
    async with database.user_transaction(principal) as connection:
        return await documents_service.rename(connection, principal, document_id, payload.title)


@router.get(
    "/documents/{document_id}/pages",
    response_model=DocumentPages,
    summary="The text extracted from a document, page by page",
    responses=_NOT_FOUND,
)
async def list_document_pages(
    document_id: UUID,
    principal: CurrentPrincipal,
    database: DatabaseDep,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> DocumentPages:
    async with database.user_transaction(principal) as connection:
        return await documents_service.list_pages(
            connection, principal, document_id, offset=offset, limit=limit
        )


@router.put(
    "/documents/{document_id}/pages/{page_number}",
    response_model=DocumentPage,
    summary="Correct the text read from a picture, while the document waits for review",
    responses={**_NOT_FOUND, **_CONFLICT},
)
async def edit_document_page(
    document_id: UUID,
    page_number: int,
    payload: PageEdit,
    principal: CurrentPrincipal,
    database: DatabaseDep,
) -> DocumentPage:
    async with database.user_transaction(principal) as connection:
        return await documents_service.edit_page(
            connection, principal, document_id, page_number, payload.text
        )


@router.post(
    "/documents/{document_id}/confirm",
    response_model=Document,
    status_code=202,
    summary="Use the extracted text as it stands: index it",
    responses={**_NOT_FOUND, **_CONFLICT, 503: {"model": ProblemDetail}},
)
async def confirm_document(
    document_id: UUID, request: Request, principal: CurrentPrincipal, database: DatabaseDep
) -> Document:
    """Queues indexing of the pages as stored (including the learner's corrections). Also the way
    to retry indexing that failed after the pages were saved."""
    async with database.user_transaction(principal) as connection:
        return await documents_service.confirm(
            connection, principal, document_id, settings=request.app.state.settings
        )


@router.post(
    "/documents/{document_id}/reprocess",
    response_model=Document,
    status_code=202,
    summary="Read the stored file again from scratch",
    responses={**_NOT_FOUND, **_CONFLICT, **_STORAGE, 429: {"model": ProblemDetail}},
)
async def reprocess_document(
    document_id: UUID,
    request: Request,
    principal: CurrentPrincipal,
    token: AccessToken,
    database: DatabaseDep,
    files: FilesDep,
) -> Document:
    """Discards the extracted text (including corrections) and processes the file again."""
    return await documents_service.reprocess(
        database,
        principal,
        token,
        files=files,
        settings=request.app.state.settings,
        document_id=document_id,
    )


@router.get(
    "/documents/{document_id}/file",
    summary="Download the original file",
    response_class=Response,
    responses={
        **_NOT_FOUND,
        200: {
            "content": {
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
            }
        },
    },
)
async def download_document(
    document_id: UUID,
    principal: CurrentPrincipal,
    token: AccessToken,
    database: DatabaseDep,
    files: FilesDep,
) -> Response:
    """Always an attachment, never displayed in the browser."""
    stored = await documents_service.download(
        database, principal, token, files=files, document_id=document_id
    )
    return Response(
        content=stored.data,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{stored.file_name}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


@router.delete(
    "/documents/{document_id}",
    status_code=204,
    summary="Delete a document, its file, its pages and its indexed passages",
    responses={**_NOT_FOUND, **_CONFLICT, **_STORAGE},
)
async def delete_document(
    document_id: UUID,
    principal: CurrentPrincipal,
    token: AccessToken,
    database: DatabaseDep,
    files: FilesDep,
) -> Response:
    await documents_service.delete_document(
        database, principal, token, files=files, document_id=document_id
    )
    return Response(status_code=204)
