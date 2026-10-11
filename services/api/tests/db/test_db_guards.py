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


SECURITY_DEFINER_CALLABLE_BY_CLIENTS = """
    select p.oid::regprocedure::text as function_name
    from pg_proc p join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'public' and p.prosecdef
      and (has_function_privilege('anon', p.oid, 'execute')
           or has_function_privilege('authenticated', p.oid, 'execute'))
    order by 1
"""


def test_no_security_definer_function_in_public_can_be_called_by_clients(
    database_dsn: str,
) -> None:
    """A SECURITY DEFINER function runs with its owner's rights. Every one that lives in `public`
    must be unreachable from the browser-facing roles, or it becomes a door around row security."""
    leaks = admin(database_dsn).fetchall(SECURITY_DEFINER_CALLABLE_BY_CLIENTS)

    assert leaks == [], f"callable by anon/authenticated: {[row['function_name'] for row in leaks]}"


def test_the_platform_helper_is_locked_when_a_hosted_project_has_it(database_dsn: str) -> None:
    """Hosted Supabase projects carry `public.rls_auto_enable()`; the migration revokes it there."""
    from support.database import MIGRATIONS_DIR

    migration = (MIGRATIONS_DIR / "20261011150000_lock_down_platform_helper.sql").read_text(
        encoding="utf-8"
    )
    database = admin(database_dsn)
    database.execute(
        "create function public.rls_auto_enable() returns event_trigger"
        " language plpgsql security definer as $$ begin null; end $$"
    )
    try:
        before = database.fetchone(
            "select has_function_privilege('anon', 'public.rls_auto_enable()', 'execute')"
            " as anon,"
            " has_function_privilege('authenticated', 'public.rls_auto_enable()', 'execute')"
            " as auth"
        )
        assert before == {"anon": True, "auth": True}, "the stub's default privileges should apply"

        database.run_script(migration)
        database.run_script(migration)  # running it twice changes nothing

        after = database.fetchone(
            "select has_function_privilege('anon', 'public.rls_auto_enable()', 'execute')"
            " as anon,"
            " has_function_privilege('authenticated', 'public.rls_auto_enable()', 'execute')"
            " as auth"
        )
        assert after == {"anon": False, "auth": False}
        assert database.fetchall(SECURITY_DEFINER_CALLABLE_BY_CLIENTS) == []
    finally:
        database.execute("drop function public.rls_auto_enable()")


def test_the_platform_helper_migration_is_harmless_where_the_helper_does_not_exist(
    database_dsn: str,
) -> None:
    from support.database import MIGRATIONS_DIR

    migration = (MIGRATIONS_DIR / "20261011150000_lock_down_platform_helper.sql").read_text(
        encoding="utf-8"
    )

    admin(database_dsn).run_script(migration)  # no error, nothing to revoke
