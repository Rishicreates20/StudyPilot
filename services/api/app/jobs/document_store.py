"""Reading and writing a document's pages, passages and status, for the worker (privileged).

Every write that belongs to a running job first takes the job's row lock and checks that this
worker still owns it (``hold_job``), then writes pages or passages and finishes the job in the SAME
transaction: a document is either fully in one state or untouched, never half-indexed. The worker
connects without row security, so every statement names the learner's ``user_id`` explicitly.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from psycopg.types.json import Jsonb

from app.core.db import SystemConnection
from app.documents.chunking import Chunk
from app.documents.extract import ExtractedPage, Warn
from app.jobs import queue
from app.jobs.errors import JobCancelled, LeaseLost
from app.jobs.queue import Job

# A document keeps at most this many warnings: a pathological file must not fill the row.
MAX_WARNINGS = 50


@dataclass(frozen=True)
class DocumentRow:
    id: UUID
    user_id: UUID
    goal_id: UUID
    goal_status: str
    title: str
    kind: str
    original_name: str | None
    mime_type: str | None
    size_bytes: int
    sha256: str
    storage_path: str
    status: str
    paginated: bool


async def load_document(
    connection: SystemConnection, user_id: UUID, document_id: UUID
) -> DocumentRow | None:
    cursor = await connection.execute(
        "select d.id, d.user_id, d.goal_id, g.status as goal_status, d.title, d.kind,"
        " d.original_name, d.mime_type, d.size_bytes, d.sha256, d.storage_path, d.status,"
        " d.paginated"
        " from public.source_documents d"
        " join public.learning_goals g on g.id = d.goal_id and g.user_id = d.user_id"
        " where d.id = %s and d.user_id = %s",
        (document_id, user_id),
    )
    row = await cursor.fetchone()
    return DocumentRow(**row) if row else None


async def hold_job(connection: SystemConnection, job: Job, worker_id: str) -> None:
    """Lock the job row and confirm this worker still owns it and nobody cancelled it."""
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


async def mark_processing(connection: SystemConnection, document: DocumentRow) -> None:
    await connection.execute(
        "update public.source_documents set status = 'processing', error_code = null,"
        " error_message = null where id = %s and user_id = %s",
        (document.id, document.user_id),
    )


def _warning_json(warnings: Sequence[Warn]) -> Jsonb:
    return Jsonb(
        [
            {"code": w.code, "message": w.message, "page": w.page}
            for w in list(warnings)[:MAX_WARNINGS]
        ]
    )


async def save_pages(
    connection: SystemConnection,
    job: Job,
    worker_id: str,
    document: DocumentRow,
    pages: Sequence[ExtractedPage],
    *,
    paginated: bool,
    page_count: int,
    warnings: Sequence[Warn],
    review: bool,
) -> None:
    """Replace the document's pages (and drop its old passages), and move it on.

    With ``review`` the document waits for the learner to look at what was read, and this job is
    finished; otherwise it stays ``processing`` for the indexing that follows in the same job.
    """
    await hold_job(connection, job, worker_id)
    await connection.execute(
        "delete from public.document_chunks where document_id = %s and user_id = %s",
        (document.id, document.user_id),
    )
    await connection.execute(
        "delete from public.document_pages where document_id = %s and user_id = %s",
        (document.id, document.user_id),
    )
    async with connection.cursor() as cursor:
        await cursor.executemany(
            "insert into public.document_pages (user_id, document_id, page_number, text, source,"
            " legibility, needs_review) values (%s, %s, %s, %s, %s, %s, %s)",
            [
                (
                    document.user_id,
                    document.id,
                    page.number,
                    page.text,
                    page.source,
                    page.legibility,
                    page.source == "ocr" and page.legibility != "clear",
                )
                for page in pages
            ],
        )
    await connection.execute(
        "update public.source_documents set status = %s, paginated = %s, page_count = %s,"
        " char_count = %s, ocr_page_count = %s, warnings = %s, chunk_count = 0,"
        " embedding_model = null, indexed_at = null, error_code = null, error_message = null"
        " where id = %s and user_id = %s",
        (
            "review" if review else "processing",
            paginated,
            page_count,
            sum(len(page.text) for page in pages),
            sum(1 for page in pages if page.source == "ocr"),
            _warning_json(warnings),
            document.id,
            document.user_id,
        ),
    )
    if review and not await queue.complete(connection, job.id, worker_id):
        raise LeaseLost  # rolls the whole transaction back


async def load_pages(
    connection: SystemConnection, user_id: UUID, document_id: UUID
) -> list[tuple[int, str]]:
    cursor = await connection.execute(
        "select page_number, text from public.document_pages"
        " where document_id = %s and user_id = %s order by page_number",
        (document_id, user_id),
    )
    return [(row["page_number"], row["text"]) for row in await cursor.fetchall()]


async def save_chunks(
    connection: SystemConnection,
    job: Job,
    worker_id: str,
    document: DocumentRow,
    chunks: Sequence[Chunk],
    vectors: Sequence[Sequence[float]],
    model: str,
) -> None:
    """Replace the document's passages with ``chunks`` and their vectors, finish it, and the job."""
    if len(chunks) != len(vectors):
        raise ValueError("every passage needs exactly one vector")
    await hold_job(connection, job, worker_id)
    await connection.execute(
        "delete from public.document_chunks where document_id = %s and user_id = %s",
        (document.id, document.user_id),
    )
    async with connection.cursor() as cursor:
        await cursor.executemany(
            "insert into public.document_chunks (user_id, goal_id, document_id, chunk_index,"
            " page_start, page_end, section_title, content, embedding, embedding_model)"
            " values (%s, %s, %s, %s, %s, %s, %s, %s, %s::extensions.vector, %s)",
            [
                (
                    document.user_id,
                    document.goal_id,
                    document.id,
                    chunk.index,
                    chunk.page_start,
                    chunk.page_end,
                    chunk.section_title,
                    chunk.text,
                    "[" + ",".join(f"{value:.8g}" for value in vector) + "]",
                    model,
                )
                for chunk, vector in zip(chunks, vectors, strict=True)
            ],
        )
    # Indexing happens only once the text is trusted (clear, or looked at by the learner).
    await connection.execute(
        "update public.document_pages set needs_review = false"
        " where document_id = %s and user_id = %s and needs_review",
        (document.id, document.user_id),
    )
    await connection.execute(
        "update public.source_documents set status = 'ready', chunk_count = %s,"
        " embedding_model = %s, indexed_at = now(), error_code = null, error_message = null"
        " where id = %s and user_id = %s",
        (len(chunks), model, document.id, document.user_id),
    )
    if not await queue.complete(connection, job.id, worker_id):
        raise LeaseLost


async def mark_failed(
    connection: SystemConnection,
    user_id: UUID,
    document_id: UUID,
    *,
    code: str,
    message: str,
    scrub_job: UUID | None = None,
) -> None:
    """Show a document as failed, with a reason the learner can read.

    Only a document that is still waiting or being processed is touched: a finished or reviewed
    document keeps what it has. ``scrub_job`` removes the signed link from that job's request.
    """
    await connection.execute(
        "update public.source_documents set status = 'failed', error_code = %s,"
        " error_message = %s where id = %s and user_id = %s"
        " and status in ('queued', 'processing')",
        (code[:60], message[:300], document_id, user_id),
    )
    if scrub_job is not None:
        await scrub_link(connection, scrub_job)


async def scrub_link(connection: SystemConnection, job_id: UUID) -> None:
    """Forget the signed link a document job carried: it is no longer needed."""
    await connection.execute(
        "update public.generation_jobs set request = request - 'object' where id = %s", (job_id,)
    )


async def settle_documents(connection: SystemConnection) -> list[UUID]:
    """Fail documents whose job ended without the worker saying so (it was reaped or cancelled).

    A document in ``queued`` or ``processing`` whose newest job is failed or cancelled would
    otherwise wait forever. Returns the documents it settled.
    """
    cursor = await connection.execute(
        """
        with latest as (
            select distinct on (document_id) document_id, status
            from public.generation_jobs
            where document_id is not null
            order by document_id, created_at desc, id desc
        )
        update public.source_documents d set
            status = 'failed',
            error_code = case when l.status = 'cancelled'
                then 'JOB_CANCELLED' else 'JOB_FAILED' end,
            error_message = case
                when l.status = 'cancelled'
                    then 'Processing was stopped. Process it again to retry.'
                else 'Processing did not finish. Process it again to retry.' end
        from latest l
        where l.document_id = d.id
          and d.status in ('queued', 'processing')
          and l.status in ('failed', 'cancelled')
        returning d.id
        """
    )
    return [row["id"] for row in await cursor.fetchall()]
