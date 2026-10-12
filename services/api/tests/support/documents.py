"""Builders for document tests: rows written straight to the database, and unit vectors."""

import hashlib
import uuid
from typing import Any

from psycopg import sql
from psycopg.types.json import Jsonb

from app.ai.fake_embedding import hashed_vector
from app.ai.provider import EMBEDDING_DIMENSIONS
from support.database import admin


def vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{value:.7f}" for value in values) + "]"


def one_hot(position: int) -> str:
    """A unit vector with a single 1: orthogonal to every other ``one_hot``."""
    values = [0.0] * EMBEDDING_DIMENSIONS
    values[position % EMBEDDING_DIMENSIONS] = 1.0
    return vector_literal(values)


def text_vector(text: str) -> str:
    """The test double's embedding of ``text``, as the literal the database takes."""
    return vector_literal(hashed_vector(text))


def sha_of(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()


def add_document(
    dsn: str,
    user: uuid.UUID,
    goal: uuid.UUID,
    *,
    title: str = "Rust notes",
    kind: str = "text",
    status: str = "ready",
    seed: str | None = None,
    **fields: Any,
) -> uuid.UUID:
    """A document row. A file kind gets a storage path under the learner's own prefix."""
    document = uuid.uuid4()
    values: dict[str, Any] = {
        "id": document,
        "user_id": user,
        "goal_id": goal,
        "title": title,
        "kind": kind,
        "original_name": "notes.txt",
        "mime_type": "text/plain",
        "size_bytes": 2048,
        "sha256": sha_of(seed or str(document)),
        "storage_path": f"{user}/{document}/notes.txt",
        "status": status,
        "paginated": kind in {"pdf", "image"},
        "page_count": 1,
    }
    if status == "ready":
        values["indexed_at"] = "now()"
    if status == "failed":
        values["error_code"] = "DOCUMENT_UNREADABLE"
        values["error_message"] = "This file could not be read."
    values.update(fields)
    now = values.pop("indexed_at", None)
    columns = list(values)
    placeholders: list[sql.Composable] = [sql.Placeholder(name) for name in columns]
    if now:
        columns.append("indexed_at")
        placeholders.append(sql.SQL("now()"))
    row = admin(dsn).fetchone(
        sql.SQL("insert into public.source_documents ({}) values ({}) returning id").format(
            sql.SQL(", ").join(sql.Identifier(name) for name in columns),
            sql.SQL(", ").join(placeholders),
        ),
        {name: (Jsonb(v) if isinstance(v, list | dict) else v) for name, v in values.items()},
    )
    assert row is not None
    return row["id"]


def add_page(
    dsn: str,
    user: uuid.UUID,
    document: uuid.UUID,
    number: int = 1,
    text: str = "Ownership means one owner.",
    *,
    source: str = "text",
    **fields: Any,
) -> uuid.UUID:
    row = admin(dsn).fetchone(
        "insert into public.document_pages (user_id, document_id, page_number, text, source,"
        " legibility, needs_review) values (%s, %s, %s, %s, %s, %s, %s) returning id",
        (
            user,
            document,
            number,
            text,
            source,
            fields.get("legibility"),
            fields.get("needs_review", False),
        ),
    )
    assert row is not None
    return row["id"]


def add_chunk(
    dsn: str,
    user: uuid.UUID,
    goal: uuid.UUID,
    document: uuid.UUID,
    index: int = 0,
    content: str = "Ownership means each value has one owner.",
    *,
    embedding: str | None = None,
    page_start: int = 1,
    page_end: int | None = None,
    section_title: str | None = None,
    model: str = "fake-embedding-1",
) -> uuid.UUID:
    row = admin(dsn).fetchone(
        "insert into public.document_chunks (user_id, goal_id, document_id, chunk_index,"
        " page_start, page_end, section_title, content, embedding, embedding_model)"
        " values (%s, %s, %s, %s, %s, %s, %s, %s, %s::extensions.vector, %s) returning id",
        (
            user,
            goal,
            document,
            index,
            page_start,
            page_end if page_end is not None else page_start,
            section_title,
            content,
            embedding or text_vector(content),
            model,
        ),
    )
    assert row is not None
    return row["id"]
