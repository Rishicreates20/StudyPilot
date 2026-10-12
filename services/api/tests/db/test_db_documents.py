"""Documents in the database: who can write what, and what is always true."""

import uuid
from dataclasses import dataclass
from typing import Any

import psycopg.errors
import pytest
from psycopg import sql

from support.database import admin, create_auth_user
from support.documents import (
    add_chunk,
    add_document,
    add_page,
    one_hot,
    sha_of,
    vector_literal,
)
from support.rows import add_goal, add_job

CONSTRAINT = (psycopg.errors.CheckViolation, psycopg.errors.ForeignKeyViolation)


@dataclass(frozen=True)
class Learner:
    user: uuid.UUID
    goal: uuid.UUID


@pytest.fixture
def ada(database_dsn: str) -> Learner:
    user = create_auth_user(database_dsn)
    return Learner(user, add_goal(database_dsn, user))


@pytest.fixture
def bob(database_dsn: str) -> Learner:
    user = create_auth_user(database_dsn)
    return Learner(user, add_goal(database_dsn, user))


def client_insert(dsn: str, who: Learner, **overrides: Any) -> dict[str, Any]:
    """Insert a document as the learner (the way the API does) and return the row it made.

    Like every ``acting_as`` block this is rolled back afterwards: it shows what the learner is
    allowed to do, and leaves nothing behind."""
    document = uuid.uuid4()
    values: dict[str, Any] = {
        "id": document,
        "user_id": who.user,
        "goal_id": who.goal,
        "title": "Notes",
        "kind": "text",
        "original_name": "notes.txt",
        "mime_type": "text/plain",
        "size_bytes": 100,
        "sha256": sha_of(str(document)),
        "storage_path": f"{who.user}/{document}/notes.txt",
        "status": "queued",
        **overrides,
    }
    with admin(dsn).acting_as("authenticated", who.user) as connection:
        row = connection.execute(
            sql.SQL("insert into public.source_documents ({}) values ({}) returning *").format(
                sql.SQL(", ").join(sql.Identifier(name) for name in values),
                sql.SQL(", ").join(sql.Placeholder(name) for name in values),
            ),
            values,
        ).fetchone()
    assert row is not None
    return dict(row)


# --- The private bucket -----------------------------------------------------------------------


def test_the_bucket_is_private_with_a_size_limit_and_a_type_allowlist(database_dsn: str) -> None:
    bucket = admin(database_dsn).fetchone("select * from storage.buckets where id = 'documents'")

    assert bucket is not None
    assert bucket["public"] is False and bucket["file_size_limit"] == 10 * 1024 * 1024
    assert set(bucket["allowed_mime_types"]) == {
        "application/pdf",
        "text/plain",
        "image/png",
        "image/jpeg",
        "image/webp",
    }


def put_object(dsn: str, role: str, who: uuid.UUID | None, name: str) -> None:
    with admin(dsn).acting_as(role, who) as connection:
        connection.execute(
            "insert into storage.objects (bucket_id, name, owner_id) values ('documents', %s, %s)",
            (name, str(who) if who else None),
        )


def test_a_learner_can_store_read_and_delete_files_under_their_own_prefix(
    database_dsn: str, ada: Learner
) -> None:
    name = f"{ada.user}/{uuid.uuid4()}/notes.txt"

    with admin(database_dsn).acting_as("authenticated", ada.user) as connection:
        connection.execute(
            "insert into storage.objects (bucket_id, name, owner_id) values ('documents', %s, %s)",
            (name, str(ada.user)),
        )
        seen = connection.execute("select name from storage.objects where bucket_id = 'documents'")
        assert [row["name"] for row in seen.fetchall()] == [name]
        deleted = connection.execute("delete from storage.objects where name = %s", (name,))
        assert deleted.rowcount == 1


def test_a_learner_cannot_store_a_file_under_someone_elses_prefix(
    database_dsn: str, ada: Learner, bob: Learner
) -> None:
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        put_object(database_dsn, "authenticated", ada.user, f"{bob.user}/{uuid.uuid4()}/x.txt")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        put_object(database_dsn, "authenticated", ada.user, f"{uuid.uuid4()}/x.txt")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        put_object(database_dsn, "authenticated", ada.user, "loose-file.txt")


def test_a_learner_cannot_see_or_delete_someone_elses_files(
    database_dsn: str, ada: Learner, bob: Learner
) -> None:
    name = f"{bob.user}/{uuid.uuid4()}/secret.txt"
    admin(database_dsn).execute(
        "insert into storage.objects (bucket_id, name, owner_id) values ('documents', %s, %s)",
        (name, str(bob.user)),
    )

    with admin(database_dsn).acting_as("authenticated", ada.user) as connection:
        assert connection.execute("select 1 from storage.objects").fetchall() == []
        assert connection.execute("delete from storage.objects").rowcount == 0
    with admin(database_dsn).acting_as("authenticated", bob.user) as connection:
        assert connection.execute("select 1 from storage.objects").rowcount == 1


def test_a_stored_file_can_never_be_overwritten_in_place(database_dsn: str, ada: Learner) -> None:
    name = f"{ada.user}/{uuid.uuid4()}/notes.txt"
    admin(database_dsn).execute(
        "insert into storage.objects (bucket_id, name, owner_id) values ('documents', %s, %s)",
        (name, str(ada.user)),
    )

    with admin(database_dsn).acting_as("authenticated", ada.user) as connection:
        updated = connection.execute("update storage.objects set name = name || 'x'")
        assert updated.rowcount == 0  # no update policy: nothing is visible to update


def test_nobody_signed_out_can_reach_the_bucket(database_dsn: str, ada: Learner) -> None:
    admin(database_dsn).execute(
        "insert into storage.objects (bucket_id, name, owner_id) values ('documents', %s, %s)",
        (f"{ada.user}/{uuid.uuid4()}/a.txt", str(ada.user)),
    )

    with admin(database_dsn).acting_as("anon") as connection:
        assert connection.execute("select 1 from storage.objects").fetchall() == []
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        put_object(database_dsn, "anon", None, f"{ada.user}/x/a.txt")


# --- source_documents: what a learner may add -------------------------------------------------


def test_a_learner_can_add_a_document_to_their_own_goal(database_dsn: str, ada: Learner) -> None:
    row = client_insert(database_dsn, ada)

    assert row["status"] == "queued" and row["chunk_count"] == 0
    assert row["warnings"] == [] and row["indexed_at"] is None and row["user_id"] == ada.user


def test_a_learner_cannot_add_a_document_for_someone_else_or_to_someone_elses_goal(
    database_dsn: str, ada: Learner, bob: Learner
) -> None:
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        client_insert(database_dsn, ada, user_id=bob.user, storage_path=f"{bob.user}/x/a.txt")
    with pytest.raises(CONSTRAINT):
        client_insert(database_dsn, ada, goal_id=bob.goal)


@pytest.mark.parametrize("status", ["processing", "review", "ready", "failed"])
def test_a_new_document_can_only_start_out_queued(
    database_dsn: str, ada: Learner, status: str
) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        client_insert(database_dsn, ada, status=status)


def test_a_file_must_live_under_the_learners_own_prefix_and_the_documents_own_folder(
    database_dsn: str, ada: Learner, bob: Learner
) -> None:
    other = uuid.uuid4()
    for path in (
        f"{bob.user}/{other}/notes.txt",  # someone else's prefix
        f"{ada.user}/{other}/notes.txt",  # not this document's folder
        "notes.txt",
    ):
        with pytest.raises(psycopg.errors.CheckViolation):
            client_insert(database_dsn, ada, storage_path=path)


def test_every_document_has_a_file_even_pasted_text(database_dsn: str, ada: Learner) -> None:
    client_insert(database_dsn, ada, kind="pasted", original_name=None, mime_type="text/plain")
    with pytest.raises(psycopg.errors.NotNullViolation):
        client_insert(database_dsn, ada, storage_path=None)


@pytest.mark.parametrize(
    "overrides",
    [
        {"title": "   "},
        {"title": "x" * 201},
        {"kind": "docx"},
        {"size_bytes": 0},
        {"size_bytes": 60_000_000},
        {"sha256": "not-a-hash"},
        {"sha256": "A" * 64},
    ],
)
def test_malformed_documents_are_refused(
    database_dsn: str, ada: Learner, overrides: dict[str, Any]
) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        client_insert(database_dsn, ada, **overrides)


def test_the_same_file_is_stored_once_per_goal_but_may_be_in_another_goal(
    database_dsn: str, ada: Learner
) -> None:
    other_goal = add_goal(database_dsn, ada.user)
    add_document(database_dsn, ada.user, ada.goal, sha256=sha_of("same"))

    with pytest.raises(psycopg.errors.UniqueViolation):
        client_insert(database_dsn, ada, sha256=sha_of("same"))
    client_insert(database_dsn, Learner(ada.user, other_goal), sha256=sha_of("same"))


def test_an_archived_goal_takes_no_new_documents(database_dsn: str, ada: Learner) -> None:
    archived = Learner(ada.user, add_goal(database_dsn, ada.user, status="archived"))

    with pytest.raises(psycopg.errors.CheckViolation, match="archived"):
        client_insert(database_dsn, archived)


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("chunk_count", 5),
        ("char_count", 5),
        ("ocr_page_count", 1),
        ("indexed_at", "2026-10-11T10:00:00Z"),
        ("error_code", "X"),
        ("error_message", "x"),
        ("embedding_model", "x"),
        ("page_count", 3),
        ("paginated", True),
    ],
)
def test_a_learner_cannot_write_the_columns_only_the_worker_sets(
    database_dsn: str, ada: Learner, column: str, value: Any
) -> None:
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        client_insert(database_dsn, ada, **{column: value})


# --- source_documents: what a learner may change ----------------------------------------------


def count_rows(dsn: str, table: str, column: str, value: object) -> int:
    """How many rows of a document table belong to ``value`` (names are test-controlled)."""
    assert table in {"source_documents", "document_pages", "document_chunks"}
    assert column in {"document_id", "user_id"}
    query = sql.SQL("select count(*) from public.{} where {} = %s").format(
        sql.Identifier(table), sql.Identifier(column)
    )
    return admin(dsn).scalar(query, (value,))


def update_as(
    dsn: str, who: Learner, document: uuid.UUID, sql: str, params: tuple[Any, ...] = ()
) -> int:
    with admin(dsn).acting_as("authenticated", who.user) as connection:
        return connection.execute(sql, (*params, document)).rowcount  # type: ignore[arg-type]


def test_a_learner_can_rename_their_document(database_dsn: str, ada: Learner) -> None:
    document = add_document(database_dsn, ada.user, ada.goal)

    assert (
        update_as(
            database_dsn,
            ada,
            document,
            "update public.source_documents set title = %s where id = %s",
            ("New name",),
        )
        == 1
    )


@pytest.mark.parametrize("old", ["review", "ready", "failed"])
def test_a_learner_can_send_a_document_to_be_processed_again(
    database_dsn: str, ada: Learner, old: str
) -> None:
    document = add_document(database_dsn, ada.user, ada.goal, status=old)

    with admin(database_dsn).acting_as("authenticated", ada.user) as connection:
        connection.execute(
            "update public.source_documents set status = 'queued' where id = %s", (document,)
        )
        row = connection.execute(
            "select status, error_code, error_message from public.source_documents where id = %s",
            (document,),
        ).fetchone()
    assert row == {"status": "queued", "error_code": None, "error_message": None}


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("queued", "ready"),
        ("queued", "review"),
        ("queued", "failed"),
        ("processing", "queued"),
        ("review", "ready"),
        ("failed", "ready"),
        ("ready", "processing"),
    ],
)
def test_every_other_change_of_status_belongs_to_the_worker(
    database_dsn: str, ada: Learner, old: str, new: str
) -> None:
    document = add_document(database_dsn, ada.user, ada.goal, status=old)

    with pytest.raises(psycopg.errors.CheckViolation, match="processed again"):
        update_as(
            database_dsn,
            ada,
            document,
            "update public.source_documents set status = %s where id = %s",
            (new,),
        )


def test_a_learner_cannot_edit_the_facts_about_a_file(database_dsn: str, ada: Learner) -> None:
    document = add_document(database_dsn, ada.user, ada.goal)

    for column, value in (
        ("size_bytes", 5),
        ("sha256", sha_of("x")),
        ("kind", "pdf"),
        ("user_id", ada.user),
        ("goal_id", ada.goal),
    ):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            update_as(
                database_dsn,
                ada,
                document,
                f"update public.source_documents set {column} = %s where id = %s",  # noqa: S608
                (value,),
            )


def test_nobody_can_change_another_learners_document(
    database_dsn: str, ada: Learner, bob: Learner
) -> None:
    document = add_document(database_dsn, bob.user, bob.goal)

    assert (
        update_as(
            database_dsn,
            ada,
            document,
            "update public.source_documents set title = 'Mine' where id = %s",
        )
        == 0
    )
    with admin(database_dsn).acting_as("authenticated", ada.user) as connection:
        assert connection.execute("select 1 from public.source_documents").fetchall() == []
        assert connection.execute("delete from public.source_documents").rowcount == 0


def test_an_archived_goals_documents_cannot_be_changed(database_dsn: str, ada: Learner) -> None:
    document = add_document(database_dsn, ada.user, ada.goal)
    admin(database_dsn).execute(
        "update public.learning_goals set status = 'archived' where id = %s", (ada.goal,)
    )

    with pytest.raises(psycopg.errors.CheckViolation, match="archived"):
        update_as(
            database_dsn,
            ada,
            document,
            "update public.source_documents set title = 'New' where id = %s",
        )


def test_a_document_that_is_being_processed_cannot_be_deleted_but_others_can(
    database_dsn: str, ada: Learner
) -> None:
    busy = add_document(database_dsn, ada.user, ada.goal, status="processing")
    done = add_document(database_dsn, ada.user, ada.goal)

    assert (
        update_as(database_dsn, ada, busy, "delete from public.source_documents where id = %s") == 0
    )
    assert (
        update_as(database_dsn, ada, done, "delete from public.source_documents where id = %s") == 1
    )


# --- Always-true rules --------------------------------------------------------------------------


def test_ready_needs_an_index_time_and_failed_needs_a_reason(
    database_dsn: str, ada: Learner
) -> None:
    ready = add_document(database_dsn, ada.user, ada.goal, status="queued")
    with pytest.raises(psycopg.errors.CheckViolation):
        admin(database_dsn).execute(
            "update public.source_documents set status = 'ready' where id = %s", (ready,)
        )
    with pytest.raises(psycopg.errors.CheckViolation):
        admin(database_dsn).execute(
            "update public.source_documents set status = 'failed' where id = %s", (ready,)
        )


# --- document_pages ---------------------------------------------------------------------------


def test_a_learner_reads_only_their_own_pages(
    database_dsn: str, ada: Learner, bob: Learner
) -> None:
    mine = add_document(database_dsn, ada.user, ada.goal)
    theirs = add_document(database_dsn, bob.user, bob.goal)
    add_page(database_dsn, ada.user, mine)
    add_page(database_dsn, bob.user, theirs)

    with admin(database_dsn).acting_as("authenticated", ada.user) as connection:
        assert connection.execute("select 1 from public.document_pages").rowcount == 1


def test_pages_are_written_only_by_the_worker(database_dsn: str, ada: Learner) -> None:
    document = add_document(database_dsn, ada.user, ada.goal, status="review")
    page = add_page(database_dsn, ada.user, document)

    for statement in (
        "insert into public.document_pages (user_id, document_id, page_number, text, source)"
        " values (%s, %s, 2, 'x', 'text')",
        "delete from public.document_pages",
        "update public.document_pages set page_number = 9",
        "update public.document_pages set source = 'text_layer'",
    ):
        with admin(database_dsn).acting_as("authenticated", ada.user) as connection:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute(statement, (ada.user, document) if "%s" in statement else None)  # type: ignore[arg-type]
    assert page


def test_a_learner_can_correct_a_pages_text_while_the_document_waits_for_review(
    database_dsn: str, ada: Learner
) -> None:
    document = add_document(database_dsn, ada.user, ada.goal, kind="image", status="review")
    page = add_page(
        database_dsn, ada.user, document, source="ocr", legibility="partly", needs_review=True
    )

    with admin(database_dsn).acting_as("authenticated", ada.user) as connection:
        connection.execute(
            "update public.document_pages set text = 'Corrected words' where id = %s", (page,)
        )
        row = connection.execute(
            "select text, edited, needs_review from public.document_pages where id = %s", (page,)
        ).fetchone()
    assert row == {"text": "Corrected words", "edited": True, "needs_review": False}


@pytest.mark.parametrize("status", ["queued", "processing", "ready", "failed"])
def test_text_cannot_be_corrected_unless_the_document_is_in_review(
    database_dsn: str, ada: Learner, status: str
) -> None:
    document = add_document(database_dsn, ada.user, ada.goal, status=status)
    page = add_page(database_dsn, ada.user, document)

    with admin(database_dsn).acting_as("authenticated", ada.user) as connection:
        with pytest.raises(psycopg.errors.CheckViolation, match="review"):
            connection.execute("update public.document_pages set text = 'x' where id = %s", (page,))


def test_page_numbers_are_unique_and_positive(database_dsn: str, ada: Learner) -> None:
    document = add_document(database_dsn, ada.user, ada.goal)
    add_page(database_dsn, ada.user, document, 1)

    with pytest.raises(psycopg.errors.UniqueViolation):
        add_page(database_dsn, ada.user, document, 1)
    with pytest.raises(psycopg.errors.CheckViolation):
        add_page(database_dsn, ada.user, document, 0)


def test_a_page_cannot_belong_to_another_learners_document(
    database_dsn: str, ada: Learner, bob: Learner
) -> None:
    theirs = add_document(database_dsn, bob.user, bob.goal)

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        add_page(database_dsn, ada.user, theirs)


# --- document_chunks --------------------------------------------------------------------------


def test_chunks_are_read_only_to_their_owner_and_invisible_to_everyone_else(
    database_dsn: str, ada: Learner, bob: Learner
) -> None:
    document = add_document(database_dsn, ada.user, ada.goal)
    add_chunk(database_dsn, ada.user, ada.goal, document)

    with admin(database_dsn).acting_as("authenticated", ada.user) as connection:
        assert connection.execute("select 1 from public.document_chunks").rowcount == 1
    with admin(database_dsn).acting_as("authenticated", bob.user) as connection:
        assert connection.execute("select 1 from public.document_chunks").fetchall() == []
    for statement in (
        "update public.document_chunks set content = 'x'",
        "delete from public.document_chunks",
        "insert into public.document_chunks (user_id) values (gen_random_uuid())",
    ):
        with admin(database_dsn).acting_as("authenticated", ada.user) as connection:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute(statement)  # type: ignore[arg-type]
    with admin(database_dsn).acting_as("anon") as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("select 1 from public.document_chunks")


@pytest.mark.parametrize("size", [0, 3, 768, 1535, 1537, 3072])
def test_a_vector_must_have_exactly_1536_numbers(
    database_dsn: str, ada: Learner, size: int
) -> None:
    document = add_document(database_dsn, ada.user, ada.goal)

    with pytest.raises(
        (
            psycopg.errors.DataException,
            psycopg.errors.InvalidParameterValue,
            psycopg.errors.ProgrammingError,
        )
    ):
        add_chunk(
            database_dsn, ada.user, ada.goal, document, embedding=vector_literal([0.5] * size)
        )


def test_a_chunk_records_its_model_and_keeps_pages_in_order(
    database_dsn: str, ada: Learner
) -> None:
    document = add_document(database_dsn, ada.user, ada.goal)

    with pytest.raises(psycopg.errors.CheckViolation):
        add_chunk(database_dsn, ada.user, ada.goal, document, model="")
    with pytest.raises(psycopg.errors.CheckViolation):
        add_chunk(database_dsn, ada.user, ada.goal, document, page_start=3, page_end=2)
    with pytest.raises(psycopg.errors.CheckViolation):
        add_chunk(database_dsn, ada.user, ada.goal, document, page_start=0)
    with pytest.raises(psycopg.errors.CheckViolation):
        add_chunk(database_dsn, ada.user, ada.goal, document, content="")


def test_a_chunk_belongs_to_one_document_goal_and_learner_together(
    database_dsn: str, ada: Learner, bob: Learner
) -> None:
    mine = add_document(database_dsn, ada.user, ada.goal)
    other_goal = add_goal(database_dsn, ada.user)

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        add_chunk(database_dsn, bob.user, bob.goal, mine)  # someone else's document
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        add_chunk(database_dsn, ada.user, other_goal, mine)  # the wrong goal of the right learner


def test_passage_numbers_are_unique_within_a_document(database_dsn: str, ada: Learner) -> None:
    document = add_document(database_dsn, ada.user, ada.goal)
    add_chunk(database_dsn, ada.user, ada.goal, document, 0)

    with pytest.raises(psycopg.errors.UniqueViolation):
        add_chunk(database_dsn, ada.user, ada.goal, document, 0)


def test_the_text_search_column_is_filled_in_by_the_database(
    database_dsn: str, ada: Learner
) -> None:
    document = add_document(database_dsn, ada.user, ada.goal)
    add_chunk(database_dsn, ada.user, ada.goal, document, 0, "Ownership means one owner at a time.")
    add_chunk(database_dsn, ada.user, ada.goal, document, 1, "Kubernetes schedules containers.")

    rows = admin(database_dsn).fetchall(
        "select chunk_index from public.document_chunks"
        " where user_id = %s and fts @@ to_tsquery('simple', 'ownership')",
        (ada.user,),
    )

    assert [row["chunk_index"] for row in rows] == [0]


def test_vectors_can_be_compared_by_cosine_distance(database_dsn: str, ada: Learner) -> None:
    document = add_document(database_dsn, ada.user, ada.goal)
    add_chunk(database_dsn, ada.user, ada.goal, document, 0, "first", embedding=one_hot(0))
    add_chunk(database_dsn, ada.user, ada.goal, document, 1, "second", embedding=one_hot(1))

    rows = admin(database_dsn).fetchall(
        "select content, embedding OPERATOR(extensions.<=>) %s::extensions.vector as distance"
        " from public.document_chunks where user_id = %s order by distance",
        (one_hot(1), ada.user),
    )

    assert [row["content"] for row in rows] == ["second", "first"]
    assert rows[0]["distance"] == pytest.approx(0.0) and rows[1]["distance"] == pytest.approx(1.0)


# --- Deletion ---------------------------------------------------------------------------------


def test_deleting_a_document_removes_its_pages_chunks_and_jobs(
    database_dsn: str, ada: Learner
) -> None:
    document = add_document(database_dsn, ada.user, ada.goal)
    add_page(database_dsn, ada.user, document)
    add_chunk(database_dsn, ada.user, ada.goal, document)
    add_job(
        database_dsn,
        ada.user,
        ada.goal,
        status="completed",
        job_type="document",
        document_id=document,
    )

    admin(database_dsn).execute("delete from public.source_documents where id = %s", (document,))

    for table in ("document_pages", "document_chunks"):
        assert count_rows(database_dsn, table, "document_id", document) == 0
    assert (
        admin(database_dsn).scalar(
            "select count(*) from public.generation_jobs where document_id = %s", (document,)
        )
        == 0
    )


def test_deleting_a_goal_removes_its_documents_and_everything_derived_from_them(
    database_dsn: str, ada: Learner
) -> None:
    document = add_document(database_dsn, ada.user, ada.goal)
    add_page(database_dsn, ada.user, document)
    add_chunk(database_dsn, ada.user, ada.goal, document)
    admin(database_dsn).execute(
        "update public.learning_goals set status = 'archived' where id = %s", (ada.goal,)
    )

    admin(database_dsn).execute("delete from public.learning_goals where id = %s", (ada.goal,))

    for table in ("source_documents", "document_pages", "document_chunks"):
        assert count_rows(database_dsn, table, "user_id", ada.user) == 0


def test_deleting_an_account_removes_every_document_row(database_dsn: str) -> None:
    user = create_auth_user(database_dsn)
    goal = add_goal(database_dsn, user)
    document = add_document(database_dsn, user, goal)
    add_page(database_dsn, user, document)
    add_chunk(database_dsn, user, goal, document)

    admin(database_dsn).execute("delete from auth.users where id = %s", (user,))

    for table in ("source_documents", "document_pages", "document_chunks"):
        assert count_rows(database_dsn, table, "user_id", user) == 0


# --- Document jobs ----------------------------------------------------------------------------

INSERT_JOB = (
    "insert into public.generation_jobs (user_id, goal_id, job_type, document_id)"
    " values (%s, %s, 'document', %s) returning *"
)


def test_a_learner_can_queue_a_job_for_their_own_document(database_dsn: str, ada: Learner) -> None:
    document = add_document(database_dsn, ada.user, ada.goal, status="queued")

    with admin(database_dsn).acting_as("authenticated", ada.user) as connection:
        job = connection.execute(INSERT_JOB, (ada.user, ada.goal, document)).fetchone()

    assert job is not None and (job["job_type"], job["status"], job["document_id"]) == (
        "document",
        "queued",
        document,
    )
    assert job["item_id"] is None and job["attempt_id"] is None


def test_a_document_job_must_name_a_document_of_the_same_goal_and_learner(
    database_dsn: str, ada: Learner, bob: Learner
) -> None:
    mine = add_document(database_dsn, ada.user, ada.goal)
    theirs = add_document(database_dsn, bob.user, bob.goal)
    other_goal = add_goal(database_dsn, ada.user)

    for who, goal, document in (
        (ada.user, ada.goal, theirs),  # someone else's document
        (ada.user, other_goal, mine),  # another goal of the same learner
        (bob.user, bob.goal, mine),  # someone else's document, their own goal
    ):
        with admin(database_dsn).acting_as("authenticated", who) as connection:
            with pytest.raises(CONSTRAINT):
                connection.execute(INSERT_JOB, (who, goal, document))


def test_a_document_job_and_its_document_always_go_together(
    database_dsn: str, ada: Learner
) -> None:
    document = add_document(database_dsn, ada.user, ada.goal)

    with admin(database_dsn).acting_as("authenticated", ada.user) as connection:
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "insert into public.generation_jobs (user_id, goal_id, job_type)"
                " values (%s, %s, 'document')",
                (ada.user, ada.goal),
            )
    with admin(database_dsn).acting_as("authenticated", ada.user) as connection:
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "insert into public.generation_jobs (user_id, goal_id, job_type, document_id)"
                " values (%s, %s, 'roadmap', %s)",
                (ada.user, ada.goal, document),
            )


def test_only_one_document_job_can_be_active_per_document(database_dsn: str, ada: Learner) -> None:
    document = add_document(database_dsn, ada.user, ada.goal, status="queued")
    admin(database_dsn).execute(INSERT_JOB, (ada.user, ada.goal, document))

    with pytest.raises(psycopg.errors.UniqueViolation):
        admin(database_dsn).execute(INSERT_JOB, (ada.user, ada.goal, document))
