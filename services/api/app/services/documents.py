"""Business rules for study documents: adding, checking, processing again, searching, deleting.

The API never reads a PDF or calls a vision model. Adding a document validates the bytes, stores
the file in private storage with the learner's own token, records the document and queues a job;
the worker does the rest. Files are never public: the worker reads through a short-lived signed
link made when the job is queued, and a learner downloads through this API as an attachment.

Calls to storage and to the model provider happen OUTSIDE database transactions, so a slow upload
never holds a connection. A file stored for a document that then could not be recorded is deleted
again (best effort), and a document row is only ever created after its file is safely stored.
"""

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import psycopg.errors
import structlog

from app.ai.provider import EMBEDDING_DIMENSIONS, EmbeddingTask, LLMError, LLMProvider
from app.core.config import Settings
from app.core.db import Database, UserConnection
from app.core.errors import (
    AppError,
    ConflictError,
    InvalidRequestError,
    NotFoundError,
    PayloadTooLargeError,
    RateLimitedError,
    ServiceUnavailableError,
    UnsupportedMediaError,
)
from app.core.rate_limit import SlidingWindowLimiter
from app.core.security import Principal
from app.documents.extract import clean_text
from app.documents.sniff import (
    Detected,
    UnsupportedFile,
    detect,
    safe_file_name,
)
from app.documents.storage import DocumentFiles, StorageError, object_path
from app.repositories import documents as documents_repo
from app.repositories import goals as goals_repo
from app.repositories import jobs as jobs_repo
from app.retrieval.search import describe_position, search_passages, similarity_bar
from app.schemas.documents import (
    Document,
    DocumentLimits,
    DocumentList,
    DocumentPage,
    DocumentPages,
    PassageHit,
    SearchRequest,
    SearchResult,
)
from app.schemas.goals import Goal

log = structlog.get_logger("app.documents")

_DAY_SECONDS = 24 * 3600
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_MAX_NAME = 200
ACCEPTED_TYPES = ["PDF", "Plain text (.txt, .md)", "Images (.png, .jpg, .webp)", "Pasted text"]


@dataclass(frozen=True)
class Download:
    data: bytes
    file_name: str
    mime_type: str


# --- Small helpers ------------------------------------------------------------------------------


def _goal_not_found() -> NotFoundError:
    return NotFoundError("Goal not found.", code="GOAL_NOT_FOUND")


def _document_not_found() -> NotFoundError:
    # Same answer for "does not exist" and "belongs to someone else".
    return NotFoundError("Document not found.", code="DOCUMENT_NOT_FOUND")


def _archived() -> ConflictError:
    return ConflictError(
        "This goal is archived. Restore it to work with its documents.", code="GOAL_ARCHIVED"
    )


def _busy() -> ConflictError:
    return ConflictError(
        "This document is being processed. Wait for it to finish, or cancel the job first.",
        code="DOCUMENT_BUSY",
    )


def storage_error(error: StorageError) -> AppError:
    """A storage failure as an HTTP error; the message is already safe to show."""
    if error.code == "FILE_TOO_LARGE":
        return PayloadTooLargeError(error.message, code="FILE_TOO_LARGE")
    if error.code == "STORAGE_NOT_FOUND":
        return NotFoundError(
            "The stored file is missing. Upload the document again.", code="FILE_MISSING"
        )
    return ServiceUnavailableError(error.message, code=error.code)


def _require_ready_to_store(settings: Settings, files: DocumentFiles | None) -> DocumentFiles:
    if files is None:
        raise ServiceUnavailableError(
            "File storage isn't set up on this server yet.", code="STORAGE_NOT_CONFIGURED"
        )
    if not settings.ai_configured:
        raise ServiceUnavailableError(
            "Reading documents needs the AI service, which isn't set up on this server yet.",
            code="AI_NOT_CONFIGURED",
        )
    return files


def display_name(filename: str | None) -> str | None:
    """The file's own name for display: no folders, no control characters, bounded."""
    if not filename:
        return None
    name = filename.replace("\\", "/").rsplit("/", 1)[-1]
    name = _CONTROL.sub("", name).strip()[:_MAX_NAME]
    return name or None


def title_for(title: str | None, filename: str | None) -> str:
    cleaned = _CONTROL.sub(" ", title or "").strip()
    if cleaned:
        return cleaned[:_MAX_NAME]
    name = display_name(filename)
    if name:
        stem = name.rsplit(".", 1)[0] if "." in name.strip(".") else name
        if stem.strip():
            return stem.strip()[:_MAX_NAME]
    return "Untitled document"


def check_detected(data: bytes, filename: str, settings: Settings) -> Detected:
    if len(data) > settings.document_max_bytes:
        raise _too_large(settings)
    try:
        return detect(data, filename)
    except UnsupportedFile as problem:
        if problem.code == "FILE_EMPTY":
            raise InvalidRequestError(problem.message, code=problem.code) from None
        raise UnsupportedMediaError(problem.message, code=problem.code) from None


def _too_large(settings: Settings) -> PayloadTooLargeError:
    megabytes = settings.document_max_bytes / (1024 * 1024)
    return PayloadTooLargeError(
        f"That file is larger than the {megabytes:g} MB limit. Upload it in parts.",
        code="FILE_TOO_LARGE",
    )


async def _forget_file(files: DocumentFiles, path: str, token: str) -> None:
    try:
        await files.delete(path, token=token)
    except StorageError as problem:
        log.warning("document.orphan_file", code=problem.code)


async def _writable_goal(
    connection: UserConnection, principal: Principal, goal_id: UUID, *, for_update: bool = False
) -> Goal:
    goal = await goals_repo.get(connection, principal.user_id, goal_id, for_update=for_update)
    if goal is None:
        raise _goal_not_found()
    if goal.status == "archived":
        raise _archived()
    return goal


async def _check_job_allowance(
    connection: UserConnection, principal: Principal, settings: Settings
) -> None:
    since = datetime.now(UTC) - timedelta(seconds=_DAY_SECONDS)
    used = await jobs_repo.count_since(connection, principal.user_id, since, "document")
    if used >= settings.document_jobs_per_user_per_day:
        raise RateLimitedError(
            f"You can process up to {settings.document_jobs_per_user_per_day} documents a day. "
            "Please try again tomorrow.",
            code="DOCUMENT_LIMIT_REACHED_TODAY",
        )


async def _check_quotas(
    connection: UserConnection, principal: Principal, settings: Settings, goal_id: UUID
) -> None:
    if (
        await documents_repo.count_for_goal(connection, principal.user_id, goal_id)
        >= settings.documents_per_goal
    ):
        raise ConflictError(
            f"A goal can hold up to {settings.documents_per_goal} documents. "
            "Delete one you no longer need first.",
            code="DOCUMENT_LIMIT_REACHED",
        )
    if (
        await documents_repo.count_for_user(connection, principal.user_id)
        >= settings.documents_per_user
    ):
        raise ConflictError(
            "You have reached the limit of stored documents. Delete some first.",
            code="DOCUMENT_LIMIT_REACHED",
        )
    await _check_job_allowance(connection, principal, settings)


async def _with_job(
    connection: UserConnection, principal: Principal, document: Document
) -> Document:
    job = await jobs_repo.latest_for_document(connection, principal.user_id, document.id)
    return document.model_copy(update={"job": job})


# --- Adding a document --------------------------------------------------------------------------


async def add_document(
    database: Database,
    principal: Principal,
    token: str,
    *,
    files: DocumentFiles | None,
    settings: Settings,
    goal_id: UUID,
    data: bytes,
    filename: str,
    title: str | None,
    pasted: bool,
) -> Document:
    """Validate, store and queue one document (an uploaded file, or pasted text)."""
    detected = check_detected(data, filename, settings)
    store = _require_ready_to_store(settings, files)
    sha256 = _sha256(data)

    async with database.user_transaction(principal) as connection:
        await _writable_goal(connection, principal, goal_id)
        await _check_quotas(connection, principal, settings, goal_id)
        if await documents_repo.find_same_file(connection, principal.user_id, goal_id, sha256):
            raise _already_added()

    document_id = uuid4()
    path = object_path(principal.user_id, document_id, safe_file_name(filename, detected.extension))
    try:
        await store.put(path, data, detected.mime_type, token=token)
        link = await store.grant_read(path, token=token)
    except StorageError as problem:
        await _forget_file(store, path, token)
        raise storage_error(problem) from None

    kind = "pasted" if pasted else detected.kind
    try:
        async with database.user_transaction(principal) as connection:
            await documents_repo.insert(
                connection,
                principal.user_id,
                document_id=document_id,
                goal_id=goal_id,
                title=title_for(title, filename),
                kind=kind,
                original_name=None if pasted else display_name(filename),
                mime_type=detected.mime_type,
                size_bytes=len(data),
                sha256=sha256,
                storage_path=path,
            )
            await jobs_repo.insert(
                connection,
                principal.user_id,
                goal_id,
                idempotency_key=None,
                request={"task": "extract", "object": link.to_json()},
                job_type="document",
                document_id=document_id,
            )
            document = await documents_repo.get(connection, principal.user_id, document_id)
            if document is None:
                raise RuntimeError("the new document could not be read back")
            document = await _with_job(connection, principal, document)
    except psycopg.errors.UniqueViolation:
        await _forget_file(store, path, token)
        raise _already_added() from None
    except Exception:
        await _forget_file(store, path, token)
        raise
    log.info(
        "document.added",
        document_id=str(document_id),
        goal_id=str(goal_id),
        kind=kind,
        size_bytes=len(data),
    )
    return document


def _already_added() -> ConflictError:
    return ConflictError("You already added this file to this goal.", code="DOCUMENT_EXISTS")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --- Reading ------------------------------------------------------------------------------------


async def list_documents(
    connection: UserConnection,
    principal: Principal,
    goal_id: UUID,
    *,
    settings: Settings,
    files: DocumentFiles | None,
) -> DocumentList:
    goal = await goals_repo.get(connection, principal.user_id, goal_id)
    if goal is None:
        raise _goal_not_found()
    documents = await documents_repo.list_for_goal(connection, principal.user_id, goal_id)
    jobs = await jobs_repo.latest_per_document(connection, principal.user_id, goal_id)
    return DocumentList(
        items=[
            document.model_copy(update={"job": jobs.get(document.id)}) for document in documents
        ],
        limits=DocumentLimits(
            max_bytes=settings.document_max_bytes,
            max_pages=settings.document_max_pages,
            max_ocr_pages=settings.document_max_ocr_pages,
            documents_per_goal=settings.documents_per_goal,
            accepted=ACCEPTED_TYPES,
        ),
        goal_archived=goal.status == "archived",
        storage_available=files is not None,
        ocr_available=settings.ai_configured and settings.document_max_ocr_pages > 0,
        indexing_available=settings.ai_configured,
    )


async def get_document(
    connection: UserConnection, principal: Principal, document_id: UUID
) -> Document:
    document = await documents_repo.get(connection, principal.user_id, document_id)
    if document is None:
        raise _document_not_found()
    return await _with_job(connection, principal, document)


async def list_pages(
    connection: UserConnection,
    principal: Principal,
    document_id: UUID,
    *,
    offset: int,
    limit: int,
) -> DocumentPages:
    ref = await documents_repo.get_ref(connection, principal.user_id, document_id)
    if ref is None:
        raise _document_not_found()
    total = await documents_repo.count_pages(connection, principal.user_id, document_id)
    items = await documents_repo.list_pages(
        connection, principal.user_id, document_id, offset=offset, limit=limit
    )
    return DocumentPages(
        items=items,
        total=total,
        offset=offset,
        limit=limit,
        editable=ref.status == "review" and ref.goal_status != "archived",
    )


# --- Changing a document ------------------------------------------------------------------------


async def rename(
    connection: UserConnection, principal: Principal, document_id: UUID, title: str
) -> Document:
    ref = await documents_repo.get_ref(connection, principal.user_id, document_id)
    if ref is None:
        raise _document_not_found()
    if ref.goal_status == "archived":
        raise _archived()
    await documents_repo.rename(connection, principal.user_id, document_id, title)
    return await get_document(connection, principal, document_id)


async def edit_page(
    connection: UserConnection,
    principal: Principal,
    document_id: UUID,
    page_number: int,
    text: str,
) -> DocumentPage:
    """Correct the text of a page read from a picture, while the document waits for review."""
    ref = await documents_repo.get_ref(connection, principal.user_id, document_id)
    if ref is None:
        raise _document_not_found()
    if ref.goal_status == "archived":
        raise _archived()
    if ref.status != "review":
        raise ConflictError(
            "Text can only be corrected while a document waits for your review.",
            code="DOCUMENT_NOT_IN_REVIEW",
        )
    try:
        page = await documents_repo.update_page_text(
            connection, principal.user_id, document_id, page_number, clean_text(text)
        )
    except psycopg.errors.CheckViolation:
        raise ConflictError(
            "Text can only be corrected while a document waits for your review.",
            code="DOCUMENT_NOT_IN_REVIEW",
        ) from None
    if page is None:
        raise NotFoundError("Page not found.", code="PAGE_NOT_FOUND")
    return page


async def confirm(
    connection: UserConnection, principal: Principal, document_id: UUID, *, settings: Settings
) -> Document:
    """Use the extracted text as it stands: queue indexing (also retries a failed indexing)."""
    if not settings.ai_configured:
        raise ServiceUnavailableError(
            "Indexing documents needs the AI service, which isn't set up on this server yet.",
            code="AI_NOT_CONFIGURED",
        )
    ref = await documents_repo.get_ref(connection, principal.user_id, document_id, for_update=True)
    if ref is None:
        raise _document_not_found()
    if ref.goal_status == "archived":
        raise _archived()
    if ref.status not in {"review", "failed"} or not ref.has_pages:
        raise ConflictError(
            "There is no extracted text waiting to be used. Process the document again instead.",
            code="NOTHING_TO_CONFIRM",
        )
    await _check_job_allowance(connection, principal, settings)
    await _queue(connection, principal, ref.goal_id, document_id, {"task": "index"})
    log.info("document.confirmed", document_id=str(document_id))
    return await get_document(connection, principal, document_id)


async def reprocess(
    database: Database,
    principal: Principal,
    token: str,
    *,
    files: DocumentFiles | None,
    settings: Settings,
    document_id: UUID,
) -> Document:
    """Read the stored file again from scratch (discarding corrections made to its text)."""
    store = _require_ready_to_store(settings, files)
    async with database.user_transaction(principal) as connection:
        ref = await documents_repo.get_ref(connection, principal.user_id, document_id)
        if ref is None:
            raise _document_not_found()
        if ref.goal_status == "archived":
            raise _archived()
        if ref.status not in {"review", "ready", "failed"}:
            raise _busy()
        await _check_job_allowance(connection, principal, settings)
        path, goal_id = ref.storage_path, ref.goal_id
    try:
        link = await store.grant_read(path, token=token)
    except StorageError as problem:
        raise storage_error(problem) from None
    async with database.user_transaction(principal) as connection:
        locked = await documents_repo.get_ref(
            connection, principal.user_id, document_id, for_update=True
        )
        if locked is None:
            raise _document_not_found()
        if locked.status not in {"review", "ready", "failed"}:
            raise _busy()
        await _queue(
            connection,
            principal,
            goal_id,
            document_id,
            {"task": "extract", "object": link.to_json()},
        )
        log.info("document.reprocess_requested", document_id=str(document_id))
        return await get_document(connection, principal, document_id)


async def _queue(
    connection: UserConnection,
    principal: Principal,
    goal_id: UUID,
    document_id: UUID,
    request: dict[str, object],
) -> None:
    try:
        if not await documents_repo.queue_for_processing(
            connection, principal.user_id, document_id
        ):
            raise _document_not_found()
        await jobs_repo.insert(
            connection,
            principal.user_id,
            goal_id,
            idempotency_key=None,
            request=request,
            job_type="document",
            document_id=document_id,
        )
    except psycopg.errors.UniqueViolation, psycopg.errors.CheckViolation:
        raise _busy() from None


# --- Deleting and downloading -------------------------------------------------------------------


async def delete_document(
    database: Database,
    principal: Principal,
    token: str,
    *,
    files: DocumentFiles | None,
    document_id: UUID,
) -> None:
    """Remove the file, then the document with its pages and passages (retention: nothing stays)."""
    async with database.user_transaction(principal) as connection:
        ref = await documents_repo.get_ref(connection, principal.user_id, document_id)
        if ref is None:
            raise _document_not_found()
        if ref.goal_status == "archived":
            raise _archived()
        if ref.status == "processing":
            raise _busy()
        path = ref.storage_path
    if files is None:
        raise ServiceUnavailableError(
            "File storage isn't set up on this server yet.", code="STORAGE_NOT_CONFIGURED"
        )
    try:
        await files.delete(path, token=token)
    except StorageError as problem:
        raise storage_error(problem) from None
    async with database.user_transaction(principal) as connection:
        deleted = await documents_repo.delete(connection, principal.user_id, document_id)
        # Not deleted but still there: processing started in the moment since we looked.
        if not deleted and await documents_repo.get_ref(connection, principal.user_id, document_id):
            raise _busy()
    log.info("document.deleted", document_id=str(document_id))


async def purge_goal_files(
    database: Database,
    principal: Principal,
    token: str,
    *,
    files: DocumentFiles | None,
    goal_id: UUID,
) -> None:
    """Delete the stored files of a goal that is about to be deleted (the rows cascade).

    Only an archived goal can be deleted, and nothing is removed for any other goal.
    """
    async with database.user_transaction(principal) as connection:
        goal = await goals_repo.get(connection, principal.user_id, goal_id)
        if goal is None:
            raise _goal_not_found()
        if goal.status != "archived":
            raise ConflictError(
                "Archive this goal before deleting it permanently.", code="GOAL_NOT_ARCHIVED"
            )
        paths = await documents_repo.storage_paths_for_goal(connection, principal.user_id, goal_id)
    if not paths:
        return
    if files is None:
        raise ServiceUnavailableError(
            "File storage isn't set up on this server, so this goal's files can't be removed.",
            code="STORAGE_NOT_CONFIGURED",
        )
    for path in paths:
        try:
            await files.delete(path, token=token)
        except StorageError as problem:
            raise storage_error(problem) from None
    log.info("document.goal_files_purged", goal_id=str(goal_id), files=len(paths))


async def download(
    database: Database,
    principal: Principal,
    token: str,
    *,
    files: DocumentFiles | None,
    document_id: UUID,
) -> Download:
    async with database.user_transaction(principal) as connection:
        ref = await documents_repo.get_ref(connection, principal.user_id, document_id)
        if ref is None:
            raise _document_not_found()
        document = await documents_repo.get(connection, principal.user_id, document_id)
    if files is None or document is None:
        raise ServiceUnavailableError(
            "File storage isn't set up on this server yet.", code="STORAGE_NOT_CONFIGURED"
        )
    try:
        data = await files.get(ref.storage_path, token=token)
    except StorageError as problem:
        raise storage_error(problem) from None
    fallback = ref.storage_path.rsplit(".", 1)[-1] if "." in ref.storage_path else "txt"
    name = safe_file_name(ref.original_name or document.title, fallback)
    return Download(
        data=data, file_name=name, mime_type=ref.mime_type or "application/octet-stream"
    )


# --- Search -------------------------------------------------------------------------------------


def _unavailable(error: LLMError) -> ServiceUnavailableError:
    return ServiceUnavailableError(error.user_message, code=error.code)


async def search(
    database: Database,
    principal: Principal,
    *,
    provider: LLMProvider | None,
    limiter: SlidingWindowLimiter,
    settings: Settings,
    goal_id: UUID,
    payload: SearchRequest,
) -> SearchResult:
    """The passages of the learner's ready documents that best answer a question (maybe none)."""
    if provider is None:
        raise ServiceUnavailableError(
            "Searching documents needs the AI service, which isn't set up on this server yet.",
            code="AI_NOT_CONFIGURED",
        )
    wanted: Sequence[UUID] | None = payload.document_ids
    async with database.user_transaction(principal) as connection:
        if await goals_repo.get(connection, principal.user_id, goal_id) is None:
            raise _goal_not_found()
        searched = await documents_repo.count_ready(connection, principal.user_id, goal_id, wanted)
    if searched == 0:
        return SearchResult(items=[], enough_evidence=False, searched_documents=0)
    if not limiter.allow(principal.user_id):
        raise RateLimitedError(
            "You're searching very quickly. Please wait a moment.",
            code="SEARCH_RATE_LIMITED",
            headers={"Retry-After": str(limiter.retry_after(principal.user_id))},
        )
    try:
        embedded = await provider.embed([payload.query], EmbeddingTask.QUERY)
    except LLMError as problem:
        log.warning("document.search_embed_failed", code=problem.code)
        raise _unavailable(problem) from None
    if len(embedded.vectors) != 1 or len(embedded.vectors[0]) != EMBEDDING_DIMENSIONS:
        raise ServiceUnavailableError(
            "The AI service returned an unusable answer. Please try again.",
            code="EMBEDDING_INVALID",
        )
    async with database.user_transaction(principal) as connection:
        found = await search_passages(
            connection,
            user_id=principal.user_id,
            goal_id=goal_id,
            query=payload.query,
            query_vector=embedded.vectors[0],
            limit=payload.limit or settings.retrieval_top_k,
            min_similarity=similarity_bar(settings.retrieval_min_similarity, provider.name),
            document_ids=wanted,
        )
    log.info("document.searched", goal_id=str(goal_id), results=len(found), documents=searched)
    return SearchResult(
        items=[
            PassageHit(
                chunk_id=passage.chunk_id,
                document_id=passage.document_id,
                document_title=passage.document_title,
                page_start=passage.page_start,
                page_end=passage.page_end,
                position=describe_position(passage),
                section_title=passage.section_title,
                content=passage.content,
                similarity=round(passage.similarity, 4),
                keyword_match=passage.keyword_match,
            )
            for passage in found
        ],
        enough_evidence=bool(found),
        searched_documents=searched,
    )
