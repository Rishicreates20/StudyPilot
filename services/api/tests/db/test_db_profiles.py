"""Profiles: creation by trigger, ownership via RLS, least-privilege grants, constraints."""

import uuid

import psycopg.errors
import pytest
from psycopg import sql
from psycopg.rows import DictRow

from support.database import admin, create_auth_user


def profile_of(dsn: str, user_id: uuid.UUID) -> DictRow | None:
    return admin(dsn).fetchone("select * from public.profiles where id = %s", (user_id,))


# --- Creation by trigger ---------------------------------------------------------------------


def test_signing_up_creates_a_profile_with_defaults(database_dsn: str) -> None:
    user_id = create_auth_user(database_dsn)

    profile = profile_of(database_dsn, user_id)

    assert profile is not None
    assert profile["display_name"] is None
    assert profile["locale"] == "en"
    assert profile["timezone"] == "Asia/Kolkata"


def test_the_display_name_from_sign_up_metadata_is_trimmed(database_dsn: str) -> None:
    user_id = create_auth_user(database_dsn, display_name="   Ada Lovelace  ")

    profile = profile_of(database_dsn, user_id)

    assert profile is not None
    assert profile["display_name"] == "Ada Lovelace"


@pytest.mark.parametrize("raw", ["", "    "])
def test_a_blank_display_name_is_stored_as_null(database_dsn: str, raw: str) -> None:
    user_id = create_auth_user(database_dsn, display_name=raw)

    profile = profile_of(database_dsn, user_id)

    assert profile is not None
    assert profile["display_name"] is None


def test_an_oversized_display_name_never_blocks_sign_up(database_dsn: str) -> None:
    """The trigger truncates instead of failing: an exception here would reject the sign-up."""
    user_id = create_auth_user(database_dsn, display_name="x" * 500)

    profile = profile_of(database_dsn, user_id)

    assert profile is not None
    assert isinstance(profile["display_name"], str)
    assert len(profile["display_name"]) == 80


def test_deleting_the_auth_user_deletes_the_profile(database_dsn: str) -> None:
    user_id = create_auth_user(database_dsn)

    admin(database_dsn).execute("delete from auth.users where id = %s", (user_id,))

    assert profile_of(database_dsn, user_id) is None


# --- Ownership (RLS) -------------------------------------------------------------------------


def test_a_user_sees_exactly_one_profile_their_own(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn, display_name="Alice")
    create_auth_user(database_dsn, display_name="Bob")

    with admin(database_dsn).acting_as("authenticated", alice) as connection:
        rows = connection.execute("select id, display_name from public.profiles").fetchall()

    assert rows == [{"id": alice, "display_name": "Alice"}]


def test_a_user_cannot_read_another_users_profile_by_id(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)
    bob = create_auth_user(database_dsn, display_name="Bob")

    with admin(database_dsn).acting_as("authenticated", alice) as connection:
        rows = connection.execute("select * from public.profiles where id = %s", (bob,)).fetchall()

    assert rows == []


def test_a_user_can_update_their_own_editable_fields(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)

    with admin(database_dsn).acting_as("authenticated", alice) as connection:
        row = connection.execute(
            "update public.profiles set display_name = 'Alice', locale = 'hi', timezone = 'UTC'"
            " where id = %s returning display_name, locale, timezone",
            (alice,),
        ).fetchone()

    assert row == {"display_name": "Alice", "locale": "hi", "timezone": "UTC"}


def test_a_user_cannot_update_another_users_profile(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)
    bob = create_auth_user(database_dsn, display_name="Bob")

    with admin(database_dsn).acting_as("authenticated", alice) as connection:
        cursor = connection.execute(
            "update public.profiles set display_name = 'hacked' where id = %s", (bob,)
        )
        assert cursor.rowcount == 0

    profile = profile_of(database_dsn, bob)
    assert profile is not None
    assert profile["display_name"] == "Bob"


def test_updating_a_profile_advances_updated_at(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)
    before = profile_of(database_dsn, alice)
    assert before is not None

    with admin(database_dsn).acting_as("authenticated", alice) as connection:
        row = connection.execute(
            "update public.profiles set display_name = 'New' where id = %s returning updated_at",
            (alice,),
        ).fetchone()

    assert row is not None
    assert row["updated_at"] > before["updated_at"]


# --- Least privilege -------------------------------------------------------------------------


@pytest.mark.parametrize("column", ["id", "created_at", "updated_at"])
def test_a_user_cannot_update_columns_they_do_not_own(database_dsn: str, column: str) -> None:
    alice = create_auth_user(database_dsn)

    with admin(database_dsn).acting_as("authenticated", alice) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                sql.SQL("update public.profiles set {c} = {c} where id = %s").format(
                    c=sql.Identifier(column)
                ),
                (alice,),
            )


def test_a_user_cannot_insert_profiles_directly(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)

    with admin(database_dsn).acting_as("authenticated", alice) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("insert into public.profiles (id) values (gen_random_uuid())")


def test_a_user_cannot_delete_profiles_directly(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)

    with admin(database_dsn).acting_as("authenticated", alice) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("delete from public.profiles where id = %s", (alice,))


def test_the_anonymous_role_cannot_touch_profiles(database_dsn: str) -> None:
    with admin(database_dsn).acting_as("anon") as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("select * from public.profiles")


# --- Constraints -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("display_name", ""),
        ("display_name", "   "),
        ("display_name", "x" * 81),
        ("locale", "EN"),
        ("locale", "english"),
        ("locale", ""),
        ("timezone", ""),
        ("timezone", "z" * 65),
    ],
)
def test_invalid_profile_values_are_rejected_by_the_database(
    database_dsn: str, column: str, value: str
) -> None:
    alice = create_auth_user(database_dsn)

    with admin(database_dsn).acting_as("authenticated", alice) as connection:
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                sql.SQL("update public.profiles set {c} = %s where id = %s").format(
                    c=sql.Identifier(column)
                ),
                (value, alice),
            )
