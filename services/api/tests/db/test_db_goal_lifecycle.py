"""Goal lifecycle in the database: edit, status transitions, archive, delete, preferences.

The API enforces these rules first and gives friendly messages. These tests prove the database
refuses the same illegal states on its own, so a bug in application code cannot create them.
"""

import itertools
import uuid
from datetime import date
from typing import Any, LiteralString, cast

import psycopg.errors
import pytest
from psycopg.rows import DictRow

from support.database import admin, create_auth_user

STATUSES = ("active", "paused", "completed", "archived")

LEGAL_TRANSITIONS = {
    ("active", "paused"),
    ("active", "completed"),
    ("active", "archived"),
    ("paused", "active"),
    ("paused", "completed"),
    ("paused", "archived"),
    ("completed", "active"),
    ("completed", "archived"),
    ("archived", "active"),
}


def add_goal(dsn: str, user_id: uuid.UUID, *, status: str = "active") -> uuid.UUID:
    """Insert a goal as the database owner (committed) and, if asked, put it in ``status``."""
    row = admin(dsn).fetchone(
        "insert into public.learning_goals (user_id, title) values (%s, 'Learn Kubernetes')"
        " returning id",
        (user_id,),
    )
    assert row is not None
    if status != "active":
        # Every state is one legal step from "active".
        admin(dsn).execute(
            "update public.learning_goals set status = %s where id = %s", (status, row["id"])
        )
    return row["id"]


def goal_of(dsn: str, goal_id: uuid.UUID) -> DictRow | None:
    return admin(dsn).fetchone("select * from public.learning_goals where id = %s", (goal_id,))


# --- Editing -----------------------------------------------------------------------------------


def test_an_owner_can_edit_every_editable_field(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)
    goal_id = add_goal(database_dsn, alice)

    with admin(database_dsn).acting_as("authenticated", alice) as connection:
        row = connection.execute(
            "update public.learning_goals set title = 'Learn Docker', description = 'Containers',"
            " goal_type = 'certification', current_level = 'beginner', target_date = '2031-01-31',"
            " daily_minutes = 45, preferred_languages = array['hi','en'],"
            " learning_preferences = array['quizzes']"
            " where id = %s and user_id = %s returning *",
            (goal_id, alice),
        ).fetchone()

    assert row is not None
    assert row["title"] == "Learn Docker"
    assert row["goal_type"] == "certification"
    assert row["target_date"] == date(2031, 1, 31)
    assert row["preferred_languages"] == ["hi", "en"]
    assert row["learning_preferences"] == ["quizzes"]
    assert row["updated_at"] > row["created_at"]  # the shared trigger keeps it current


def test_another_user_cannot_edit_the_goal(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)
    bob = create_auth_user(database_dsn)
    goal_id = add_goal(database_dsn, alice)

    with admin(database_dsn).acting_as("authenticated", bob) as connection:
        # Row Level Security hides the row from Bob, so the UPDATE simply matches nothing.
        result = connection.execute(
            "update public.learning_goals set title = 'Hijacked' where id = %s", (goal_id,)
        )
        assert result.rowcount == 0

    goal = goal_of(database_dsn, goal_id)
    assert goal is not None and goal["title"] == "Learn Kubernetes"


@pytest.mark.parametrize(
    "assignment",
    [
        "id = gen_random_uuid()",
        "user_id = gen_random_uuid()",
        "created_at = now() - interval '1 year'",
        "updated_at = now() - interval '1 year'",
        "completed_at = now()",
        "archived_at = now()",
    ],
)
def test_clients_cannot_write_columns_the_system_owns(database_dsn: str, assignment: str) -> None:
    alice = create_auth_user(database_dsn)
    goal_id = add_goal(database_dsn, alice)

    with admin(database_dsn).acting_as("authenticated", alice) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                cast(
                    LiteralString,
                    f"update public.learning_goals set {assignment} where id = %s",  # noqa: S608
                ),
                (goal_id,),
            )


def test_a_user_cannot_hand_a_goal_to_someone_else(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)
    bob = create_auth_user(database_dsn)
    goal_id = add_goal(database_dsn, alice)

    with admin(database_dsn).acting_as("authenticated", alice) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "update public.learning_goals set user_id = %s where id = %s", (bob, goal_id)
            )


def test_the_anonymous_role_cannot_edit_or_delete_goals(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)
    goal_id = add_goal(database_dsn, alice, status="archived")

    for statement in (
        "update public.learning_goals set title = 'x' where id = %s",
        "delete from public.learning_goals where id = %s",
    ):
        with admin(database_dsn).acting_as("anon") as connection:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute(statement, (goal_id,))


# --- Status transitions ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("current", "target"),
    [pair for pair in itertools.product(STATUSES, STATUSES) if pair[0] != pair[1]],
)
def test_status_changes_follow_the_allowed_transitions(
    database_dsn: str, current: str, target: str
) -> None:
    alice = create_auth_user(database_dsn)
    goal_id = add_goal(database_dsn, alice, status=current)

    with admin(database_dsn).acting_as("authenticated", alice) as connection:
        if (current, target) in LEGAL_TRANSITIONS:
            row = connection.execute(
                "update public.learning_goals set status = %s where id = %s returning status",
                (target, goal_id),
            ).fetchone()
            assert row is not None and row["status"] == target
        else:
            with pytest.raises(psycopg.errors.CheckViolation) as raised:
                connection.execute(
                    "update public.learning_goals set status = %s where id = %s", (target, goal_id)
                )
            assert raised.value.diag.constraint_name == "learning_goals_status_transition"


def test_setting_the_status_it_already_has_is_harmless(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)
    goal_id = add_goal(database_dsn, alice, status="paused")

    with admin(database_dsn).acting_as("authenticated", alice) as connection:
        row = connection.execute(
            "update public.learning_goals set status = 'paused' where id = %s returning status",
            (goal_id,),
        ).fetchone()

    assert row is not None and row["status"] == "paused"


def test_an_unknown_status_is_rejected(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)
    goal_id = add_goal(database_dsn, alice)

    with admin(database_dsn).acting_as("authenticated", alice) as connection:
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "update public.learning_goals set status = 'deleted' where id = %s", (goal_id,)
            )


# --- Timestamps maintained by the database ------------------------------------------------------


def test_completing_a_goal_stamps_it_and_reopening_clears_the_stamp(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)
    goal_id = add_goal(database_dsn, alice)

    with admin(database_dsn).acting_as("authenticated", alice) as connection:
        done = connection.execute(
            "update public.learning_goals set status = 'completed' where id = %s returning *",
            (goal_id,),
        ).fetchone()
        reopened = connection.execute(
            "update public.learning_goals set status = 'active' where id = %s returning *",
            (goal_id,),
        ).fetchone()

    assert done is not None and done["completed_at"] is not None
    assert done["archived_at"] is None
    assert reopened is not None and reopened["completed_at"] is None


def test_archiving_stamps_the_goal_and_restoring_clears_the_stamp(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)
    goal_id = add_goal(database_dsn, alice, status="completed")

    with admin(database_dsn).acting_as("authenticated", alice) as connection:
        archived = connection.execute(
            "update public.learning_goals set status = 'archived' where id = %s returning *",
            (goal_id,),
        ).fetchone()
        restored = connection.execute(
            "update public.learning_goals set status = 'active' where id = %s returning *",
            (goal_id,),
        ).fetchone()

    assert archived is not None
    assert archived["archived_at"] is not None
    assert archived["completed_at"] is None  # a goal is in one state at a time
    assert restored is not None
    assert restored["archived_at"] is None and restored["completed_at"] is None


@pytest.mark.parametrize("status", ["completed", "archived"])
def test_a_goal_created_in_a_late_state_still_gets_its_timestamp(
    database_dsn: str, status: str
) -> None:
    alice = create_auth_user(database_dsn)
    row = admin(database_dsn).fetchone(
        "insert into public.learning_goals (user_id, title, status) values (%s, 'Imported', %s)"
        " returning *",
        (alice, status),
    )

    assert row is not None
    stamp = "completed_at" if status == "completed" else "archived_at"
    assert row[stamp] is not None


@pytest.mark.parametrize(
    "assignment",
    ["completed_at = now()", "archived_at = now()"],
)
def test_a_timestamp_that_disagrees_with_the_status_is_refused_even_for_the_owner_role(
    database_dsn: str, assignment: str
) -> None:
    """Independent of grants: the CHECK constraints hold for every role, including the owner."""
    alice = create_auth_user(database_dsn)
    goal_id = add_goal(database_dsn, alice)

    with pytest.raises(psycopg.errors.CheckViolation):
        admin(database_dsn).execute(
            cast(
                LiteralString,
                f"update public.learning_goals set {assignment} where id = %s",  # noqa: S608
            ),
            (goal_id,),
        )


# --- Archived goals are read-only ---------------------------------------------------------------


@pytest.mark.parametrize(
    "assignment",
    [
        "title = 'Renamed'",
        "description = 'New'",
        "goal_type = 'exam'",
        "current_level = 'advanced'",
        "target_date = '2031-01-01'",
        "daily_minutes = 90",
        "preferred_languages = array['hi']",
        "learning_preferences = array['quizzes']",
    ],
)
def test_an_archived_goal_cannot_be_edited(database_dsn: str, assignment: str) -> None:
    alice = create_auth_user(database_dsn)
    goal_id = add_goal(database_dsn, alice, status="archived")

    with admin(database_dsn).acting_as("authenticated", alice) as connection:
        with pytest.raises(psycopg.errors.CheckViolation) as raised:
            connection.execute(
                cast(
                    LiteralString,
                    f"update public.learning_goals set {assignment} where id = %s",  # noqa: S608
                ),
                (goal_id,),
            )
    assert raised.value.diag.constraint_name == "learning_goals_archived_read_only"


def test_a_restored_goal_can_be_edited_again(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)
    goal_id = add_goal(database_dsn, alice, status="archived")

    with admin(database_dsn).acting_as("authenticated", alice) as connection:
        connection.execute(
            "update public.learning_goals set status = 'active' where id = %s", (goal_id,)
        )
        row = connection.execute(
            "update public.learning_goals set title = 'Renamed' where id = %s returning title",
            (goal_id,),
        ).fetchone()

    assert row is not None and row["title"] == "Renamed"


# --- Deleting ----------------------------------------------------------------------------------


def test_an_owner_can_delete_an_archived_goal(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)
    goal_id = add_goal(database_dsn, alice, status="archived")

    with admin(database_dsn).acting_as("authenticated", alice) as connection:
        result = connection.execute("delete from public.learning_goals where id = %s", (goal_id,))
        assert result.rowcount == 1


@pytest.mark.parametrize("status", ["active", "paused", "completed"])
def test_a_goal_that_is_not_archived_cannot_be_deleted(database_dsn: str, status: str) -> None:
    alice = create_auth_user(database_dsn)
    goal_id = add_goal(database_dsn, alice, status=status)

    with admin(database_dsn).acting_as("authenticated", alice) as connection:
        result = connection.execute("delete from public.learning_goals where id = %s", (goal_id,))
        assert result.rowcount == 0  # the policy hides it from DELETE

    assert goal_of(database_dsn, goal_id) is not None


def test_another_user_cannot_delete_an_archived_goal(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)
    bob = create_auth_user(database_dsn)
    goal_id = add_goal(database_dsn, alice, status="archived")

    with admin(database_dsn).acting_as("authenticated", bob) as connection:
        result = connection.execute("delete from public.learning_goals where id = %s", (goal_id,))
        assert result.rowcount == 0

    assert goal_of(database_dsn, goal_id) is not None


# --- Learning preferences ----------------------------------------------------------------------

VALID_PREFERENCES: list[list[str]] = [
    [],
    ["examples"],
    ["quizzes", "revision"],
    ["examples", "quizzes", "revision"],
]
INVALID_PREFERENCES: list[Any] = [
    ["flashcards"],
    ["examples", "examples"],
    ["examples", "quizzes", "revision", "examples"],
    ["EXAMPLES"],
    ["examples", None],
    None,
]


def test_a_new_goal_defaults_to_every_kind_of_practice(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)
    goal = goal_of(database_dsn, add_goal(database_dsn, alice))

    assert goal is not None
    assert goal["learning_preferences"] == ["examples", "quizzes", "revision"]


@pytest.mark.parametrize("preferences", VALID_PREFERENCES)
def test_valid_learning_preferences_are_accepted(database_dsn: str, preferences: list[str]) -> None:
    alice = create_auth_user(database_dsn)
    row = admin(database_dsn).fetchone(
        "insert into public.learning_goals (user_id, title, learning_preferences)"
        " values (%s, 'Goal', %s) returning learning_preferences",
        (alice, preferences),
    )

    assert row is not None and row["learning_preferences"] == preferences


@pytest.mark.parametrize("preferences", INVALID_PREFERENCES)
def test_invalid_learning_preferences_are_rejected(database_dsn: str, preferences: Any) -> None:
    alice = create_auth_user(database_dsn)

    with pytest.raises((psycopg.errors.CheckViolation, psycopg.errors.NotNullViolation)):
        admin(database_dsn).execute(
            "insert into public.learning_goals (user_id, title, learning_preferences)"
            " values (%s, 'Goal', %s)",
            (alice, preferences),
        )
