"""SQL for a learner's own study documents. Data access only; the rules live in the service.

A learner can add a document, rename it, send it to be processed again, correct the text of a
page that waits for review, and delete it. Pages, passages and every status beyond ``queued`` are
the worker's: the database grants forbid writing them from here. Every function filters by
``user_id`` as well as relying on Row Level Security.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from app.core.db import UserConnection
from app.schemas.documents import Document, DocumentPage

_COLUMNS = """
    d.id, d.goal_id, d.title, d.kind, d.original_name, d.size_bytes, d.status, d.error_code,
    d.error_message, d.paginated, d.page_count, d.chunk_count, d.char_count, d.ocr_page_count,
    d.warnings, d.embedding_model, d.indexed_at, d.created_at, d.updated_at,
    (d.status = 'review') as needs_review
"""


@dataclass(frozen=True)
class DocumentRef:
    """What the service needs to act on one document, including where its file is stored."""

    id: UUID
    goal_id: UUID
    goal_status: str
    kind: str
    status: str
    storage_path: str
    mime_type: str | None
    original_name: str | None
    size_bytes: int
    has_pages: bool


async def insert(
    connection: UserConnection,
    user_id: UUID,
    *,
    document_id: UUID,
    goal_id: UUID,
    title: str,
    kind: str,
    original_name: str | None,
    mime_type: str,
    size_bytes: int,
    sha256: str,
    storage_path: str,
) -> None:
    await connection.execute(
        "insert into public.source_documents (id, user_id, goal_id, title, kind, original_name,"
        " mime_type, size_bytes, sha256, storage_path, status)"
        " values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'queued')",
        (
            document_id,
            user_id,
            goal_id,
            title,
            kind,
            original_name,
            mime_type,
            size_bytes,
            sha256,
            storage_path,
        ),
    )


async def get(connection: UserConnection, user_id: UUID, document_id: UUID) -> Document | None:
    cursor = await connection.execute(
        f"select {_COLUMNS} from public.source_documents d"  # noqa: S608 - module constant
        " where d.id = %s and d.user_id = %s",
        (document_id, user_id),
    )
    row = await cursor.fetchone()
    return Document.model_validate(row) if row else None


async def get_ref(
    connection: UserConnection, user_id: UUID, document_id: UUID, *, for_update: bool = False
) -> DocumentRef | None:
    lock = " for update of d" if for_update else ""
    cursor = await connection.execute(
        "select d.id, d.goal_id, g.status as goal_status, d.kind, d.status, d.storage_path,"  # noqa: S608
        " d.mime_type, d.original_name, d.size_bytes,"
        " exists (select 1 from public.document_pages p where p.document_id = d.id"
        "         and p.user_id = d.user_id) as has_pages"
        " from public.source_documents d"
        " join public.learning_goals g on g.id = d.goal_id and g.user_id = d.user_id"
        f" where d.id = %s and d.user_id = %s{lock}",
        (document_id, user_id),
    )
    row = await cursor.fetchone()
    return DocumentRef(**row) if row else None


async def list_for_goal(connection: UserConnection, user_id: UUID, goal_id: UUID) -> list[Document]:
    cursor = await connection.execute(
        f"select {_COLUMNS} from public.source_documents d"  # noqa: S608 - module constant
        " where d.goal_id = %s and d.user_id = %s order by d.created_at desc, d.id",
        (goal_id, user_id),
    )
    return [Document.model_validate(row) for row in await cursor.fetchall()]


async def storage_paths_for_goal(
    connection: UserConnection, user_id: UUID, goal_id: UUID
) -> list[str]:
    cursor = await connection.execute(
        "select storage_path from public.source_documents where goal_id = %s and user_id = %s",
        (goal_id, user_id),
    )
    return [row["storage_path"] for row in await cursor.fetchall()]


async def count_for_goal(connection: UserConnection, user_id: UUID, goal_id: UUID) -> int:
    cursor = await connection.execute(
        "select count(*) as total from public.source_documents where goal_id = %s and user_id = %s",
        (goal_id, user_id),
    )
    row = await cursor.fetchone()
    return int(row["total"]) if row else 0


async def count_for_user(connection: UserConnection, user_id: UUID) -> int:
    cursor = await connection.execute(
        "select count(*) as total from public.source_documents where user_id = %s", (user_id,)
    )
    row = await cursor.fetchone()
    return int(row["total"]) if row else 0


async def find_same_file(
    connection: UserConnection, user_id: UUID, goal_id: UUID, sha256: str
) -> UUID | None:
    """The learner's document in this goal with identical bytes, if there is one."""
    cursor = await connection.execute(
        "select id from public.source_documents"
        " where user_id = %s and goal_id = %s and sha256 = %s",
        (user_id, goal_id, sha256),
    )
    row = await cursor.fetchone()
    return row["id"] if row else None


async def rename(connection: UserConnection, user_id: UUID, document_id: UUID, title: str) -> bool:
    cursor = await connection.execute(
        "update public.source_documents set title = %s where id = %s and user_id = %s",
        (title, document_id, user_id),
    )
    return cursor.rowcount == 1


async def queue_for_processing(
    connection: UserConnection, user_id: UUID, document_id: UUID
) -> bool:
    """Send a document to be processed (again); the database allows it from a settled state."""
    cursor = await connection.execute(
        "update public.source_documents set status = 'queued' where id = %s and user_id = %s",
        (document_id, user_id),
    )
    return cursor.rowcount == 1


async def delete(connection: UserConnection, user_id: UUID, document_id: UUID) -> bool:
    cursor = await connection.execute(
        "delete from public.source_documents where id = %s and user_id = %s",
        (document_id, user_id),
    )
    return cursor.rowcount == 1


async def count_pages(connection: UserConnection, user_id: UUID, document_id: UUID) -> int:
    cursor = await connection.execute(
        "select count(*) as total from public.document_pages"
        " where document_id = %s and user_id = %s",
        (document_id, user_id),
    )
    row = await cursor.fetchone()
    return int(row["total"]) if row else 0


async def list_pages(
    connection: UserConnection, user_id: UUID, document_id: UUID, *, offset: int, limit: int
) -> list[DocumentPage]:
    cursor = await connection.execute(
        "select page_number, text, source, legibility, needs_review, edited"
        " from public.document_pages where document_id = %s and user_id = %s"
        " order by page_number offset %s limit %s",
        (document_id, user_id, offset, limit),
    )
    return [DocumentPage.model_validate(row) for row in await cursor.fetchall()]


async def update_page_text(
    connection: UserConnection, user_id: UUID, document_id: UUID, page_number: int, text: str
) -> DocumentPage | None:
    """Correct one page. The database allows this only while the document waits for review."""
    cursor = await connection.execute(
        "update public.document_pages set text = %s"
        " where document_id = %s and user_id = %s and page_number = %s"
        " returning page_number, text, source, legibility, needs_review, edited",
        (text, document_id, user_id, page_number),
    )
    row = await cursor.fetchone()
    return DocumentPage.model_validate(row) if row else None


async def count_ready(
    connection: UserConnection,
    user_id: UUID,
    goal_id: UUID,
    document_ids: Sequence[UUID] | None = None,
) -> int:
    """Ready documents of a goal (or, of those named, the ones that are ready and the learner's)."""
    cursor = await connection.execute(
        "select count(*) as total from public.source_documents"
        " where goal_id = %s and user_id = %s and status = 'ready'"
        " and (%s::uuid[] is null or id = any(%s::uuid[]))",
        (
            goal_id,
            user_id,
            list(document_ids) if document_ids is not None else None,
            list(document_ids) if document_ids is not None else None,
        ),
    )
    row = await cursor.fetchone()
    return int(row["total"]) if row else 0
