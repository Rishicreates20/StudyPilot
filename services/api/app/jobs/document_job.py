"""Running one document job: read the file, extract its pages, and index them for retrieval.

Two tasks share the job type (``request["task"]``):

* ``extract`` (the default): download the file through the signed link the API made when it queued
  the job, check it is still the file that was uploaded (size, SHA-256 and signature, again),
  extract its pages, read pages that have no text layer with the vision model, and store the pages.
  If any page was read from a picture and the model was not sure of it, the document waits for the
  learner to check the text (status ``review``) and the job ends there; otherwise the job goes on
  to ``index``.
* ``index``: cut the stored pages into passages, embed them, and replace the document's passages
  and vectors in one transaction, so a document is never half-indexed.

Stages: loading 5 -> reading 15 -> extracting 30 -> reading_pages 30..60 -> saving_pages 65 ->
chunking 70 -> embedding 75..95 -> saving 98 -> done. A retry starts the task again: pages and
passages are replaced, never duplicated.
"""

import asyncio
import hashlib
from collections.abc import Sequence
from urllib.parse import unquote
from uuid import UUID

import structlog

from app.ai.calls import CallRecord, Observer, call_embed, call_ocr
from app.ai.provider import (
    EMBEDDING_DIMENSIONS,
    EmbeddingResult,
    EmbeddingTask,
    LLMError,
    LLMNotConfigured,
    LLMProvider,
    LLMRateLimited,
    OcrUnavailable,
)
from app.documents.chunking import chunk_pages, embedding_input
from app.documents.extract import (
    ExtractedPage,
    Extraction,
    ExtractionFailed,
    Warn,
    extract_pdf,
    extract_text_file,
    single_page_pdf,
)
from app.documents.sniff import UnsupportedFile, detect
from app.documents.storage import ObjectRef, StorageError
from app.jobs import document_store, queue
from app.jobs.document_store import DocumentRow
from app.jobs.errors import JobFailure
from app.jobs.queue import Job
from app.jobs.runtime import Lease, WorkerEnv, set_stage

log = structlog.get_logger("app.jobs")

OCR_PROMPT_VERSION = "ocr-transcriber/v1"
# Passages embedded per request. Small enough that one request stays well inside a per-minute
# token allowance (a free-tier key has about 30,000 a minute), large enough to be quick.
_EMBED_BATCH = 24
# A rate-limited embedding request is waited out here, inside the job: the allowance recovers
# within a minute, and failing the job instead would embed every passage again from the first one
# and spend the same allowance twice. Bounded: after this many waits the job fails and is retried.
_MAX_RATE_LIMIT_WAITS = 8
_DEFAULT_WAIT_SECONDS = 20.0
_MIN_WAIT_SECONDS = 2.0
_MAX_WAIT_SECONDS = 65.0


async def run_document(env: WorkerEnv, job: Job, lease: Lease) -> None:
    await set_stage(env, job, "loading", 5)
    lease.check()
    if job.document_id is None:  # the database forbids this; stay safe if it ever happens
        raise JobFailure("DOCUMENT_UNAVAILABLE", "This job has no document.")
    async with env.database.system_session() as connection:
        document = await document_store.load_document(connection, job.user_id, job.document_id)
    if document is None:
        raise JobFailure("DOCUMENT_UNAVAILABLE", "This document no longer exists.")
    if document.goal_status == "archived":
        raise JobFailure(
            "GOAL_UNAVAILABLE", "This goal is archived. Restore it to process its documents."
        )
    try:
        if job.request.get("task") == "index":
            async with env.database.system_session() as connection:
                await document_store.mark_processing(connection, document)
            await _index(env, job, lease, document)
        else:
            review = await _extract(env, job, lease, document)
            if not review:
                await _index(env, job, lease, document)
    except ExtractionFailed as failure:
        raise JobFailure(failure.code, failure.message, retryable=failure.retryable) from None
    except UnsupportedFile as failure:
        raise JobFailure(failure.code, failure.message) from None
    except StorageError as failure:
        raise JobFailure(failure.code, failure.message, retryable=failure.retryable) from None
    # The signed link is of no further use once the job has ended well.
    async with env.database.system_session() as connection:
        await document_store.scrub_link(connection, job.id)


def _observer(env: WorkerEnv, job: Job) -> Observer:
    async def observe(record: CallRecord) -> None:
        async with env.database.system_session() as connection:
            await queue.record_usage(connection, job, record)

    return observe


async def _extract(env: WorkerEnv, job: Job, lease: Lease, document: DocumentRow) -> bool:
    """Store the document's pages. Returns True if it now waits for the learner's review."""
    settings = env.settings
    async with env.database.system_session() as connection:
        await document_store.mark_processing(connection, document)
    await set_stage(env, job, "reading", 15)
    if env.files is None:
        raise JobFailure("STORAGE_NOT_CONFIGURED", "File storage isn't set up on this server.")
    ref = ObjectRef.from_json(job.request.get("object"))
    # The link must name THIS document's file: a job request is data and may be wrong or forged.
    if ref is None or document.storage_path not in unquote(ref.value):
        raise JobFailure(
            "FILE_LINK_MISSING",
            "The link to read this file is no longer valid. Process the document again.",
        )
    data = await env.files.read(ref)
    lease.check()

    # The file is checked again here: it came from storage, not from the request that was checked.
    if len(data) != document.size_bytes or hashlib.sha256(data).hexdigest() != document.sha256:
        raise JobFailure(
            "FILE_CHANGED", "The stored file is not the one that was uploaded. Upload it again."
        )
    if len(data) > settings.document_max_bytes:
        raise JobFailure("DOCUMENT_TOO_LARGE", "This file is larger than the limit.")
    detected = detect(data, document.original_name or "")
    if detected.kind != ("text" if document.kind == "pasted" else document.kind):
        raise JobFailure(
            "FILE_TYPE_MISMATCH", "The stored file is not the kind of file that was uploaded."
        )

    await set_stage(env, job, "extracting", 30)
    extraction: Extraction
    if detected.kind == "text":
        extraction = await asyncio.to_thread(
            extract_text_file, data, max_chars=settings.document_max_chars
        )
    elif detected.kind == "pdf":
        extraction = await asyncio.to_thread(
            extract_pdf,
            data,
            max_pages=settings.document_max_pages,
            max_chars=settings.document_max_chars,
        )
    else:
        extraction = Extraction(
            pages=[ExtractedPage(number=1, text="", source="ocr", needs_ocr=True)],
            paginated=True,
            page_count=1,
        )
    lease.check()

    pages = list(extraction.pages)
    warnings = list(extraction.warnings)
    wanted = [index for index, page in enumerate(pages) if page.needs_ocr]
    if wanted:
        pages, ocr_warnings = await _read_pages(
            env, job, lease, data, detected.mime_type, pages, wanted
        )
        warnings.extend(ocr_warnings)

    if not any(page.text.strip() for page in pages):
        raise JobFailure(
            "DOCUMENT_EMPTY", "No text could be read from this file. Try a clearer copy."
        )
    review = any(
        page.source == "ocr" and page.text.strip() and page.legibility != "clear" for page in pages
    )
    await set_stage(env, job, "saving_pages", 65)
    lease.check()
    async with env.database.system_session() as connection:
        await document_store.save_pages(
            connection,
            job,
            env.worker_id,
            document,
            pages,
            paginated=extraction.paginated,
            page_count=extraction.page_count,
            warnings=warnings,
            review=review,
        )
    log.info(
        "document.pages_saved",
        job_id=str(job.id),
        document_id=str(document.id),
        pages=len(pages),
        ocr_pages=sum(1 for page in pages if page.source == "ocr"),
        review=review,
    )
    return review


async def _read_pages(
    env: WorkerEnv,
    job: Job,
    lease: Lease,
    data: bytes,
    mime_type: str,
    pages: list[ExtractedPage],
    wanted: Sequence[int],
) -> tuple[list[ExtractedPage], list[Warn]]:
    """Have the vision model read the pages that have no text layer (bounded in number)."""
    settings = env.settings
    warnings: list[Warn] = []
    result = list(pages)
    has_text = any(page.text.strip() for page in pages if not page.needs_ocr)
    provider = env.provider
    limit = settings.document_max_ocr_pages
    skipped = [result[index].number for index in wanted[limit:]]
    chosen = list(wanted[:limit])
    if skipped:
        shown = ", ".join(str(n) for n in skipped[:10]) + (" and more" if len(skipped) > 10 else "")
        warnings.append(
            Warn(
                "OCR_LIMIT",
                f"Only the first {limit} pages without text were read. Not read: {shown}.",
                skipped[0],
            )
        )
    if provider is None or limit == 0:
        if not has_text:
            raise JobFailure(
                "AI_NOT_CONFIGURED" if provider is None else "OCR_UNAVAILABLE",
                "Reading text from images or scans isn't available on this server.",
            )
        warnings.append(
            Warn("OCR_UNAVAILABLE", "Pages without text could not be read on this server.", None)
        )
        return result, warnings

    observe = _observer(env, job)
    unread: list[int] = []
    for position, index in enumerate(chosen):
        page = result[index]
        await set_stage(env, job, "reading_pages", 30 + round(30 * position / max(1, len(chosen))))
        lease.check()
        try:
            image, mime = (
                (data, mime_type)
                if mime_type != "application/pdf"
                else (await asyncio.to_thread(single_page_pdf, data, page.number), mime_type)
            )
            reading = await call_ocr(
                provider, image, mime, prompt_version=OCR_PROMPT_VERSION, observer=observe
            )
        except OcrUnavailable:
            if not has_text:
                raise
            unread.append(page.number)
            continue
        except LLMError as error:
            if error.retryable or not has_text:
                raise
            unread.append(page.number)
            continue
        text = reading.text.strip()
        if reading.legibility == "none" or not text:
            warnings.append(
                Warn(
                    "PAGE_NOT_READABLE",
                    f"No readable text was found on page {page.number}.",
                    page.number,
                )
            )
            continue
        result[index] = ExtractedPage(
            number=page.number,
            text=text,
            source="ocr",
            legibility=reading.legibility,
        )
        if reading.legibility != "clear":
            warnings.append(
                Warn(
                    "OCR_UNCERTAIN",
                    f"Page {page.number} was read from a picture and some words may be wrong. "
                    "Check it before relying on it.",
                    page.number,
                )
            )
    if unread:
        shown = ", ".join(str(n) for n in unread[:10])
        warnings.append(Warn("OCR_UNAVAILABLE", f"Pages {shown} could not be read.", unread[0]))
    return result, warnings


async def _index(env: WorkerEnv, job: Job, lease: Lease, document: DocumentRow) -> None:
    """Cut the stored pages into passages, embed them and store them, finishing the job."""
    settings = env.settings
    await set_stage(env, job, "chunking", 70)
    async with env.database.system_session() as connection:
        pages = await document_store.load_pages(connection, document.user_id, document.id)
    chunks = await asyncio.to_thread(
        chunk_pages,
        [(number, text) for number, text in pages if text.strip()],
        target=settings.chunk_target_chars,
        overlap=settings.chunk_overlap_chars,
    )
    if not chunks:
        raise JobFailure("DOCUMENT_EMPTY", "There is no text in this document to index.")
    provider = env.provider
    if provider is None:
        raise JobFailure("AI_NOT_CONFIGURED", LLMNotConfigured.user_message)

    observe = _observer(env, job)
    inputs = [embedding_input(document.title, chunk) for chunk in chunks]
    vectors: list[list[float]] = []
    model = ""
    for start in range(0, len(inputs), _EMBED_BATCH):
        progress = 75 + round(20 * start / len(inputs))
        await set_stage(env, job, "embedding", progress)
        lease.check()
        result = await _embed_patiently(
            env, job, lease, provider, inputs[start : start + _EMBED_BATCH], progress, observe
        )
        if model and result.model_id != model:
            raise JobFailure(
                "EMBEDDING_MODEL_CHANGED",
                "The embedding model changed mid-document.",
                retryable=True,
            )
        model = result.model_id
        vectors.extend(result.vectors)
    if len(vectors) != len(chunks) or any(len(v) != EMBEDDING_DIMENSIONS for v in vectors):
        raise JobFailure(
            "EMBEDDING_INVALID", "The embedding service returned vectors of the wrong size."
        )

    await set_stage(env, job, "saving", 98)
    lease.check()
    async with env.database.system_session() as connection:
        await document_store.save_chunks(
            connection, job, env.worker_id, document, chunks, vectors, model
        )
    log.info(
        "job.completed",
        job_id=str(job.id),
        document_id=str(document.id),
        passages=len(chunks),
        model=model,
    )


async def _embed_patiently(
    env: WorkerEnv,
    job: Job,
    lease: Lease,
    provider: LLMProvider,
    texts: Sequence[str],
    progress: int,
    observe: Observer,
) -> EmbeddingResult:
    """Embed one batch, waiting out a rate limit (for as long as the service asks) up to a bound.

    A daily-allowance error is not a rate limit: it is raised at once (waiting would not help).
    """
    for waits in range(_MAX_RATE_LIMIT_WAITS + 1):
        try:
            return await call_embed(
                provider, texts, EmbeddingTask.DOCUMENT, purpose="embed.document", observer=observe
            )
        except LLMRateLimited as limited:
            if waits == _MAX_RATE_LIMIT_WAITS:
                raise
            delay = min(
                max(limited.retry_after or _DEFAULT_WAIT_SECONDS, _MIN_WAIT_SECONDS),
                _MAX_WAIT_SECONDS,
            )
        log.info(
            "document.embedding_rate_limited",
            job_id=str(job.id),
            wait_seconds=round(delay),
            wait_number=waits + 1,
        )
        await set_stage(env, job, "waiting_rate_limit", progress)
        remaining = delay
        while remaining > 0:
            step = min(1.0, remaining)
            await env.sleep(step)  # in short steps, so a cancel or a lost lease is noticed
            remaining -= step
            lease.check()
    raise AssertionError("unreachable")  # pragma: no cover


def document_id_of(job: Job) -> UUID | None:
    return job.document_id
