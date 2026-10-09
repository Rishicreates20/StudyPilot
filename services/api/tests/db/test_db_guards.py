"""Guards that protect every FUTURE migration, not just today's two tables.

These read the catalog, so a table added later without Row Level Security, or one that anonymous
visitors can reach, fails the build the moment it appears.
"""

import pytest

from support.database import admin

TABLE_PRIVILEGES = ("select", "insert", "update", "delete", "truncate", "references", "trigger")


def public_tables(dsn: str) -> list[str]:
    rows = admin(dsn).fetchall(
        "select c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace"
        " where n.nspname = 'public' and c.relkind in ('r', 'p') order by 1"
    )
    return [row["relname"] for row in rows]


def role_privilege_leaks(dsn: str, role: str, privilege: str) -> list[str]:
    return [
        table
        for table in public_tables(dsn)
        if admin(dsn).scalar(
            "select has_table_privilege(%s, %s, %s)", (role, f"public.{table}", privilege)
        )
    ]


def test_there_are_application_tables_to_check(database_dsn: str) -> None:
    assert {"profiles", "learning_goals"} <= set(public_tables(database_dsn))


def test_every_public_table_has_row_level_security_enabled(database_dsn: str) -> None:
    unprotected = admin(database_dsn).fetchall(
        "select c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace"
        " where n.nspname = 'public' and c.relkind in ('r', 'p') and not c.relrowsecurity"
    )

    assert unprotected == [], f"Tables without RLS: {[row['relname'] for row in unprotected]}"


@pytest.mark.parametrize("privilege", TABLE_PRIVILEGES)
def test_the_anonymous_role_holds_no_privileges_on_any_public_table(
    database_dsn: str, privilege: str
) -> None:
    assert role_privilege_leaks(database_dsn, "anon", privilege) == []


@pytest.mark.parametrize("privilege", ["truncate", "references", "trigger"])
def test_authenticated_never_holds_administrative_privileges(
    database_dsn: str, privilege: str
) -> None:
    assert role_privilege_leaks(database_dsn, "authenticated", privilege) == []


def test_the_signup_trigger_function_is_not_callable_by_clients(database_dsn: str) -> None:
    row = admin(database_dsn).fetchone(
        "select has_function_privilege('authenticated', 'public.handle_new_user()', 'execute')"
        " as authenticated_can,"
        " has_function_privilege('anon', 'public.handle_new_user()', 'execute') as anon_can"
    )

    assert row == {"authenticated_can": False, "anon_can": False}
