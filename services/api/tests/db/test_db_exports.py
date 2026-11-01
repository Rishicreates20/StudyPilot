"""Exports in the database (the recovered migration 20261013100000_exports.sql, ADR-049).

Who can write what, and what is always true, whatever the application does.
"""

import uuid
from typing import Any

import psycopg.errors
import pytest
from psycopg import sql

from support.database import admin, create_auth_user
from support.lessons import Seeded, add_lesson_job, seed_learning_state
from support.rows import add_goal, add_lesson

INSERT_LESSON_EXPORT = (
    "insert into public.exports (user_id, lesson_id, format, template_version)"
    " values (%s, %s, %s, 'v1') returning id, goal_id"
)
INSERT_ROADMAP_EXPORT = (
    "insert into public.exports (user_id, roadmap_id, format, template_version)"
    " values (%s, %s, %s, 'v1') returning id, goal_id"
)
CONSTRAINT_VIOLATIONS = (
    psycopg.errors.CheckViolation,
    psycopg.errors.ForeignKeyViolation,
    psycopg.errors.NotNullViolation,
)


@pytest.fixture
def seeded(database_dsn: str) -> Seeded:
    return seed_learning_state(database_dsn)


@pytest.fixture
def lesson(database_dsn: str, seeded: Seeded) -> uuid.UUID:
    job = add_lesson_job(database_dsn, seeded, seeded.topics[0], status="completed")
    return add_lesson(database_dsn, seeded.user, seeded.roadmap, seeded.topics[0], job)


def add_export(dsn: str, seeded: Seeded, lesson: uuid.UUID, fmt: str = "notes_pdf") -> uuid.UUID:
    row = admin(dsn).fetchone(INSERT_LESSON_EXPORT, (seeded.user, lesson, fmt))
    assert row is not None
    return row["id"]


def ready_values(seeded: Seeded, export: uuid.UUID) -> dict[str, Any]:
    return {
        "storage_path": f"{seeded.user}/{export}/file.pdf",
        "file_name": "notes.pdf",
        "content_type": "application/pdf",
        "size_bytes": 1000,
        "sha256": "a" * 64,
        "page_count": 3,
        "unsupported_characters": 0,
    }


def mark_ready(dsn: str, seeded: Seeded, export: uuid.UUID, **overrides: Any) -> None:
    values = {**ready_values(seeded, export), **overrides}
    admin(dsn).execute(
        "update public.exports set storage_path = %(storage_path)s, file_name = %(file_name)s,"
        " content_type = %(content_type)s, size_bytes = %(size_bytes)s, sha256 = %(sha256)s,"
        " page_count = %(page_count)s, unsupported_characters = %(unsupported_characters)s,"
        " ready_at = now() where id = %(id)s",
        {**values, "id": export},
    )


# --- Creating an export --------------------------------------------------------------------------


def test_a_learner_can_export_their_lesson_and_the_goal_comes_from_the_lesson(
    database_dsn: str, seeded: Seeded, lesson: uuid.UUID
) -> None:
    with admin(database_dsn).acting_as("authenticated", seeded.user) as connection:
        row = connection.execute(
            INSERT_LESSON_EXPORT, (seeded.user, lesson, "notes_pdf")
        ).fetchone()
    assert row is not None and row["goal_id"] == seeded.goal


def test_a_learner_can_export_their_roadmap(database_dsn: str, seeded: Seeded) -> None:
    with admin(database_dsn).acting_as("authenticated", seeded.user) as connection:
        row = connection.execute(
            INSERT_ROADMAP_EXPORT, (seeded.user, seeded.roadmap, "roadmap_pdf")
        ).fetchone()
    assert row is not None and row["goal_id"] == seeded.goal


def test_a_learner_cannot_export_someone_elses_lesson(
    database_dsn: str, seeded: Seeded, lesson: uuid.UUID
) -> None:
    mallory = create_auth_user(database_dsn)
    with (
        pytest.raises(CONSTRAINT_VIOLATIONS),
        admin(database_dsn).acting_as("authenticated", mallory) as connection,
    ):
        connection.execute(INSERT_LESSON_EXPORT, (mallory, lesson, "notes_pdf"))


def test_a_learner_cannot_choose_the_goal_of_an_export(
    database_dsn: str, seeded: Seeded, lesson: uuid.UUID
) -> None:
    other_goal = add_goal(database_dsn, seeded.user)
    with (
        pytest.raises(psycopg.errors.InsufficientPrivilege),
        admin(database_dsn).acting_as("authenticated", seeded.user) as connection,
    ):
        connection.execute(
            "insert into public.exports (user_id, goal_id, lesson_id, format, template_version)"
            " values (%s, %s, %s, 'notes_pdf', 'v1')",
            (seeded.user, other_goal, lesson),
        )


@pytest.mark.parametrize(
    ("statement", "fmt"),
    [(INSERT_LESSON_EXPORT, "roadmap_pdf"), (INSERT_ROADMAP_EXPORT, "notes_pdf")],
)
def test_the_format_must_fit_the_source(
    database_dsn: str, seeded: Seeded, lesson: uuid.UUID, statement: str, fmt: str
) -> None:
    source = lesson if statement is INSERT_LESSON_EXPORT else seeded.roadmap
    with pytest.raises(psycopg.errors.CheckViolation):
        admin(database_dsn).execute(statement, (seeded.user, source, fmt))  # type: ignore[arg-type]


def test_one_export_per_source_format_and_template_version(
    database_dsn: str, seeded: Seeded, lesson: uuid.UUID
) -> None:
    add_export(database_dsn, seeded, lesson)
    with pytest.raises(psycopg.errors.UniqueViolation):
        add_export(database_dsn, seeded, lesson)
    add_export(database_dsn, seeded, lesson, "slides_pptx")  # another format is another export


# --- What a learner may and may not write -------------------------------------------------------


@pytest.mark.parametrize("column", ["storage_path", "file_name", "size_bytes", "ready_at"])
def test_a_learner_cannot_write_the_file_details(
    database_dsn: str, seeded: Seeded, lesson: uuid.UUID, column: str
) -> None:
    export = add_export(database_dsn, seeded, lesson)
    value: Any = {"size_bytes": 1, "ready_at": "2026-10-23"}.get(column, "x")
    with (
        pytest.raises(psycopg.errors.InsufficientPrivilege),
        admin(database_dsn).acting_as("authenticated", seeded.user) as connection,
    ):
        connection.execute(
            sql.SQL("update public.exports set {} = %s where id = %s").format(
                sql.Identifier(column)
            ),
            (value, export),
        )


def test_a_learner_can_give_an_upload_capability_but_never_read_it_back(
    database_dsn: str, seeded: Seeded, lesson: uuid.UUID
) -> None:
    export = add_export(database_dsn, seeded, lesson)
    with admin(database_dsn).acting_as("authenticated", seeded.user) as connection:
        changed = connection.execute(
            "update public.exports set upload_token = 'grant' where id = %s returning id",
            (export,),
        ).fetchall()
    assert len(changed) == 1
    with (
        pytest.raises(psycopg.errors.InsufficientPrivilege),
        admin(database_dsn).acting_as("authenticated", seeded.user) as connection,
    ):
        connection.execute("select upload_token from public.exports")


def test_no_upload_capability_can_be_set_once_the_file_is_ready(
    database_dsn: str, seeded: Seeded, lesson: uuid.UUID
) -> None:
    export = add_export(database_dsn, seeded, lesson)
    mark_ready(database_dsn, seeded, export)
    with admin(database_dsn).acting_as("authenticated", seeded.user) as connection:
        changed = connection.execute(
            "update public.exports set upload_token = 'grant' where id = %s returning id",
            (export,),
        ).fetchall()
    assert changed == []  # the policy hides ready exports from this update


def test_exports_are_invisible_to_other_learners_and_anon(
    database_dsn: str, seeded: Seeded, lesson: uuid.UUID
) -> None:
    export = add_export(database_dsn, seeded, lesson)
    mallory = create_auth_user(database_dsn)
    with admin(database_dsn).acting_as("authenticated", mallory) as connection:
        assert connection.execute("select id from public.exports").fetchall() == []
        assert (
            connection.execute(
                "delete from public.exports where id = %s returning id", (export,)
            ).fetchall()
            == []
        )
    with (
        pytest.raises(psycopg.errors.InsufficientPrivilege),
        admin(database_dsn).acting_as("anon") as connection,
    ):
        connection.execute("select id from public.exports")


def test_a_learner_can_delete_their_export(
    database_dsn: str, seeded: Seeded, lesson: uuid.UUID
) -> None:
    export = add_export(database_dsn, seeded, lesson)
    with admin(database_dsn).acting_as("authenticated", seeded.user) as connection:
        deleted = connection.execute(
            "delete from public.exports where id = %s returning id", (export,)
        ).fetchall()
    assert len(deleted) == 1


# --- What is always true about a ready export ----------------------------------------------------


def test_file_details_are_all_set_together(
    database_dsn: str, seeded: Seeded, lesson: uuid.UUID
) -> None:
    export = add_export(database_dsn, seeded, lesson)
    with pytest.raises(psycopg.errors.CheckViolation):
        admin(database_dsn).execute(
            "update public.exports set file_name = 'x.pdf' where id = %s", (export,)
        )


def test_a_file_must_live_under_the_learners_own_prefix_and_its_export(
    database_dsn: str, seeded: Seeded, lesson: uuid.UUID
) -> None:
    export = add_export(database_dsn, seeded, lesson)
    someone = uuid.uuid4()
    with pytest.raises(psycopg.errors.CheckViolation):
        mark_ready(database_dsn, seeded, export, storage_path=f"{someone}/{export}/file.pdf")


def test_the_content_type_must_fit_the_format(
    database_dsn: str, seeded: Seeded, lesson: uuid.UUID
) -> None:
    export = add_export(database_dsn, seeded, lesson)
    pptx = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    with pytest.raises(psycopg.errors.CheckViolation):
        mark_ready(database_dsn, seeded, export, content_type=pptx)


# --- Jobs -----------------------------------------------------------------------------------------


def queue_export_job(dsn: str, who: uuid.UUID, goal: uuid.UUID, export: uuid.UUID) -> None:
    with admin(dsn).acting_as("authenticated", who) as connection:
        connection.execute(
            "insert into public.generation_jobs (user_id, goal_id, job_type, export_id)"
            " values (%s, %s, 'export', %s)",
            (who, goal, export),
        )


def test_a_learner_can_queue_a_job_for_their_export(
    database_dsn: str, seeded: Seeded, lesson: uuid.UUID
) -> None:
    export = add_export(database_dsn, seeded, lesson)
    queue_export_job(database_dsn, seeded.user, seeded.goal, export)


def test_an_export_job_must_name_an_export_of_the_same_goal(
    database_dsn: str, seeded: Seeded, lesson: uuid.UUID
) -> None:
    export = add_export(database_dsn, seeded, lesson)
    other_goal = add_goal(database_dsn, seeded.user)
    with pytest.raises(psycopg.errors.CheckViolation):
        queue_export_job(database_dsn, seeded.user, other_goal, export)


def test_at_most_one_active_job_per_export(
    database_dsn: str, seeded: Seeded, lesson: uuid.UUID
) -> None:
    export = add_export(database_dsn, seeded, lesson)
    admin(database_dsn).execute(
        "insert into public.generation_jobs (user_id, goal_id, job_type, export_id)"
        " values (%s, %s, 'export', %s)",
        (seeded.user, seeded.goal, export),
    )
    with pytest.raises(psycopg.errors.UniqueViolation):
        admin(database_dsn).execute(
            "insert into public.generation_jobs (user_id, goal_id, job_type, export_id)"
            " values (%s, %s, 'export', %s)",
            (seeded.user, seeded.goal, export),
        )


def test_deleting_the_goal_removes_its_exports_and_their_jobs(
    database_dsn: str, seeded: Seeded, lesson: uuid.UUID
) -> None:
    export = add_export(database_dsn, seeded, lesson)
    admin(database_dsn).execute(
        "insert into public.generation_jobs (user_id, goal_id, job_type, export_id)"
        " values (%s, %s, 'export', %s)",
        (seeded.user, seeded.goal, export),
    )
    admin(database_dsn).execute("delete from public.learning_goals where id = %s", (seeded.goal,))
    assert (
        admin(database_dsn).scalar("select count(*) from public.exports where id = %s", (export,))
        == 0
    )
    assert (
        admin(database_dsn).scalar(
            "select count(*) from public.generation_jobs where export_id = %s", (export,)
        )
        == 0
    )
