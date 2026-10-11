"""Profile preferences and onboarding state: defaults, ownership, constraints, backfill."""

import uuid
from pathlib import Path
from typing import Any, LiteralString, cast

import psycopg.errors
import pytest

from support.database import MIGRATIONS_DIR, admin, create_auth_user

MIGRATION = MIGRATIONS_DIR / "20261010100000_goal_lifecycle_and_preferences.sql"


def profile_of(dsn: str, user_id: uuid.UUID) -> dict[str, Any]:
    row = admin(dsn).fetchone("select * from public.profiles where id = %s", (user_id,))
    assert row is not None
    return dict(row)


# --- Defaults ----------------------------------------------------------------------------------


def test_a_new_profile_starts_with_sensible_preferences_and_is_not_onboarded(
    database_dsn: str,
) -> None:
    profile = profile_of(database_dsn, create_auth_user(database_dsn))

    assert profile["onboarding_completed_at"] is None
    assert profile["default_daily_minutes"] == 60
    assert profile["preferred_languages"] == ["en"]
    assert profile["learning_preferences"] == ["examples", "quizzes", "revision"]


# --- Ownership and privileges ------------------------------------------------------------------


def test_an_owner_can_save_their_preferences_and_finish_onboarding(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)

    with admin(database_dsn).acting_as("authenticated", alice) as connection:
        row = connection.execute(
            "update public.profiles set default_daily_minutes = 90,"
            " preferred_languages = array['hi','en'], learning_preferences = array['quizzes'],"
            " onboarding_completed_at = now() where id = %s returning *",
            (alice,),
        ).fetchone()

    assert row is not None
    assert row["default_daily_minutes"] == 90
    assert row["preferred_languages"] == ["hi", "en"]
    assert row["learning_preferences"] == ["quizzes"]
    assert row["onboarding_completed_at"] is not None


def test_another_user_cannot_change_someones_preferences(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)
    bob = create_auth_user(database_dsn)

    with admin(database_dsn).acting_as("authenticated", bob) as connection:
        result = connection.execute(
            "update public.profiles set default_daily_minutes = 480 where id = %s", (alice,)
        )
        assert result.rowcount == 0

    assert profile_of(database_dsn, alice)["default_daily_minutes"] == 60


def test_the_anonymous_role_cannot_read_or_change_preferences(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)

    for statement in (
        "select default_daily_minutes from public.profiles",
        "update public.profiles set default_daily_minutes = 480",
    ):
        with admin(database_dsn).acting_as("anon") as connection:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute(statement)

    assert profile_of(database_dsn, alice)["default_daily_minutes"] == 60


# --- Constraints -------------------------------------------------------------------------------

INVALID: list[tuple[str, Any]] = [
    ("default_daily_minutes", 9),
    ("default_daily_minutes", 481),
    ("preferred_languages", []),
    ("preferred_languages", ["english"]),
    ("preferred_languages", ["en", "hi", "or", "bn", "ta", "te"]),
    ("learning_preferences", ["flashcards"]),
    ("learning_preferences", ["quizzes", "quizzes"]),
]


@pytest.mark.parametrize(("column", "value"), INVALID)
def test_invalid_preferences_are_rejected_by_the_database(
    database_dsn: str, column: str, value: Any
) -> None:
    alice = create_auth_user(database_dsn)

    with admin(database_dsn).acting_as("authenticated", alice) as connection:
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                cast(
                    LiteralString,
                    f"update public.profiles set {column} = %s where id = %s",  # noqa: S608
                ),
                (value, alice),
            )


def test_an_empty_set_of_learning_preferences_is_a_valid_choice(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)

    with admin(database_dsn).acting_as("authenticated", alice) as connection:
        row = connection.execute(
            "update public.profiles set learning_preferences = '{}' where id = %s"
            " returning learning_preferences",
            (alice,),
        ).fetchone()

    assert row is not None and row["learning_preferences"] == []


# --- The backfill in the migration -------------------------------------------------------------


def test_the_migration_backfill_marks_existing_goal_owners_as_onboarded(database_dsn: str) -> None:
    """Runs the migration's own UPDATE: people who already made goals skip onboarding."""
    text = Path(MIGRATION).read_text(encoding="utf-8")
    statement = text[text.index("update public.profiles as p") :]
    with_goal = create_auth_user(database_dsn)
    without_goal = create_auth_user(database_dsn)
    admin(database_dsn).execute(
        "insert into public.learning_goals (user_id, title) values (%s, 'Existing goal')",
        (with_goal,),
    )

    admin(database_dsn).run_script(statement)

    assert profile_of(database_dsn, with_goal)["onboarding_completed_at"] is not None
    assert profile_of(database_dsn, without_goal)["onboarding_completed_at"] is None
