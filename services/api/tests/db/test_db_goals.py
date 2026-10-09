"""Learning goals: ownership via RLS, least-privilege grants, constraints, cascade."""

import uuid
from typing import Any

import psycopg.errors
import pytest
from psycopg import sql

from support.database import admin, create_auth_user

INSERT_GOAL = (
    "insert into public.learning_goals (user_id, title) values (%s, %s)"
    " returning id, title, status, goal_type, current_level, daily_minutes, preferred_languages,"
    " target_date, created_at"
)


def add_goal(dsn: str, user_id: uuid.UUID, title: str = "Learn Kubernetes") -> uuid.UUID:
    """Insert a goal as the database owner and commit it."""
    row = admin(dsn).fetchone(
        "insert into public.learning_goals (user_id, title) values (%s, %s) returning id",
        (user_id, title),
    )
    assert row is not None
    return row["id"]


# --- Creating goals --------------------------------------------------------------------------


def test_a_user_can_create_a_goal_for_themselves_and_defaults_apply(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)

    with admin(database_dsn).acting_as("authenticated", alice) as connection:
        goal = connection.execute(INSERT_GOAL, (alice, "Learn Kubernetes")).fetchone()

    assert goal is not None
    assert goal["status"] == "active"
    assert goal["goal_type"] == "general"
    assert goal["current_level"] == "unknown"  # never a guessed level
    assert goal["daily_minutes"] == 60
    assert goal["preferred_languages"] == ["en"]
    assert goal["target_date"] is None
    assert goal["created_at"] is not None


def test_a_user_cannot_create_a_goal_owned_by_someone_else(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)
    bob = create_auth_user(database_dsn)

    with admin(database_dsn).acting_as("authenticated", alice) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="row-level security"):
            connection.execute(INSERT_GOAL, (bob, "Forged for Bob"))


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("id", "00000000-0000-4000-8000-000000000001"),
        ("status", "archived"),
        ("created_at", "2020-01-01"),
        ("updated_at", "2020-01-01"),
    ],
)
def test_a_user_cannot_choose_server_owned_columns_on_insert(
    database_dsn: str, column: str, value: str
) -> None:
    alice = create_auth_user(database_dsn)

    with admin(database_dsn).acting_as("authenticated", alice) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                sql.SQL(
                    "insert into public.learning_goals (user_id, title, {c}) values (%s, 'x', {v})"
                ).format(c=sql.Identifier(column), v=sql.Literal(value)),
                (alice,),
            )


def test_a_goal_for_a_user_without_a_profile_is_rejected(database_dsn: str) -> None:
    ghost = uuid.uuid4()

    with admin(database_dsn).acting_as("authenticated", ghost) as connection:
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            connection.execute(INSERT_GOAL, (ghost, "No such user"))


# --- Reading goals ---------------------------------------------------------------------------


def test_a_user_sees_only_their_own_goals(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)
    bob = create_auth_user(database_dsn)
    alices_goal = add_goal(database_dsn, alice, "Alice's goal")
    add_goal(database_dsn, bob, "Bob's goal")

    with admin(database_dsn).acting_as("authenticated", alice) as connection:
        rows = connection.execute("select id from public.learning_goals").fetchall()

    assert rows == [{"id": alices_goal}]


def test_a_user_cannot_read_another_users_goal_by_id(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)
    bob = create_auth_user(database_dsn)
    bobs_goal = add_goal(database_dsn, bob)

    with admin(database_dsn).acting_as("authenticated", alice) as connection:
        rows = connection.execute(
            "select * from public.learning_goals where id = %s", (bobs_goal,)
        ).fetchall()

    assert rows == []


def test_a_query_that_forgets_its_user_filter_still_cannot_leak(database_dsn: str) -> None:
    """The point of RLS: the database refuses even when application code is careless."""
    alice = create_auth_user(database_dsn)
    bob = create_auth_user(database_dsn)
    add_goal(database_dsn, bob, "Bob's secret goal")

    with admin(database_dsn).acting_as("authenticated", alice) as connection:
        count = connection.execute("select count(*) as n from public.learning_goals").fetchone()

    assert count == {"n": 0}


# --- Least privilege -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "statement",
    [
        sql.SQL("select * from public.learning_goals"),
        sql.SQL(
            "insert into public.learning_goals (user_id, title) values (gen_random_uuid(), 'x')"
        ),
    ],
)
def test_the_anonymous_role_cannot_read_or_write_goals(
    database_dsn: str, statement: sql.SQL
) -> None:
    with admin(database_dsn).acting_as("anon") as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(statement)


@pytest.mark.parametrize(
    "statement",
    [
        sql.SQL("update public.learning_goals set title = 'changed' where id = %s"),
        sql.SQL("delete from public.learning_goals where id = %s"),
    ],
)
def test_clients_cannot_update_or_delete_goals_yet(database_dsn: str, statement: sql.SQL) -> None:
    """Editing arrives with its endpoint and its own migration; no grant exists until then."""
    alice = create_auth_user(database_dsn)
    goal = add_goal(database_dsn, alice)

    with admin(database_dsn).acting_as("authenticated", alice) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(statement, (goal,))


# --- Constraints -----------------------------------------------------------------------------

INVALID_VALUES: list[tuple[str, Any]] = [
    ("title", ""),
    ("title", "    "),
    ("title", "t" * 201),
    ("description", "d" * 2001),
    ("goal_type", "hobby"),
    ("current_level", "expert"),
    ("daily_minutes", 4),
    ("daily_minutes", 1441),
    ("preferred_languages", []),
    ("preferred_languages", ["en", "hi", "or", "bn", "ta", "te"]),
    ("preferred_languages", ["EN"]),
    ("preferred_languages", ["english"]),
    ("preferred_languages", ["en", None]),
]


@pytest.mark.parametrize(("column", "value"), INVALID_VALUES)
def test_invalid_goal_values_are_rejected_by_the_database(
    database_dsn: str, column: str, value: Any
) -> None:
    alice = create_auth_user(database_dsn)
    values: dict[str, Any] = {"title": "A fine title", column: value}
    columns = sql.SQL(", ").join(sql.Identifier(name) for name in ["user_id", *values])
    placeholders = sql.SQL(", ").join(sql.Placeholder() for _ in range(1 + len(values)))

    with admin(database_dsn).acting_as("authenticated", alice) as connection:
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                sql.SQL("insert into public.learning_goals ({c}) values ({p})").format(
                    c=columns, p=placeholders
                ),
                (alice, *values.values()),
            )


@pytest.mark.parametrize(
    "goal_type", ["exam", "academic_subject", "professional_skill", "certification", "interview"]
)
def test_every_documented_goal_type_is_accepted(database_dsn: str, goal_type: str) -> None:
    alice = create_auth_user(database_dsn)

    with admin(database_dsn).acting_as("authenticated", alice) as connection:
        row = connection.execute(
            "insert into public.learning_goals (user_id, title, goal_type) values (%s, 'x', %s)"
            " returning goal_type",
            (alice, goal_type),
        ).fetchone()

    assert row == {"goal_type": goal_type}


def test_language_list_validation_function(database_dsn: str) -> None:
    def valid(languages: list[str | None] | None) -> Any:
        return admin(database_dsn).scalar(
            "select public.is_valid_language_list(%s::text[])", (languages,)
        )

    assert valid(["en"]) is True
    assert valid(["en", "hi", "or"]) is True
    assert valid([]) is False
    assert valid(None) is False
    assert valid(["en", None]) is False
    assert valid(["EN"]) is False


# --- Structure -------------------------------------------------------------------------------


def test_goals_expose_a_composite_key_for_future_child_tables(database_dsn: str) -> None:
    """Child tables reference (id, user_id), which makes a cross-user parent impossible."""
    definition = admin(database_dsn).scalar(
        "select pg_get_constraintdef(oid) from pg_constraint"
        " where conname = 'learning_goals_id_user_id_key'"
    )

    assert definition == "UNIQUE (id, user_id)"


def test_deleting_a_user_deletes_their_goals(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)
    goal = add_goal(database_dsn, alice)

    admin(database_dsn).execute("delete from auth.users where id = %s", (alice,))

    remaining = admin(database_dsn).scalar(
        "select count(*) from public.learning_goals where id = %s", (goal,)
    )
    assert remaining == 0
