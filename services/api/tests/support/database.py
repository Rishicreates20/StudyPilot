"""A throwaway PostgreSQL for the test suite.

By default the suite starts a real PostgreSQL (the ``pgserver`` wheel, run by the tiny helper in
``tests/pg_server`` on Python 3.12) on a free port, so the genuine production code path (psycopg,
the connection pool, role switching, Row Level Security, true concurrency) runs without Docker.
Set ``TEST_DATABASE_URL`` to use an existing, EMPTY PostgreSQL instead (for example a CI service,
or the database of a local Supabase stack).

The real migration files in ``supabase/migrations`` are applied on top of a minimal emulation of
Supabase's roles and ``auth`` schema (``supabase_stub.sql``). A separate CI job applies the same
migrations to the genuine Supabase stack.
"""

import json
import os
import queue
import subprocess
import sys
import threading
import uuid
from collections.abc import Generator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any, LiteralString, cast

import psycopg
from psycopg import sql
from psycopg.rows import DictRow, dict_row
from psycopg.types.json import Jsonb

_SUPPORT_DIR = Path(__file__).resolve().parent
SERVER_DIR = _SUPPORT_DIR.parent / "pg_server"
STUB_SQL = _SUPPORT_DIR / "supabase_stub.sql"
MIGRATIONS_DIR = _SUPPORT_DIR.parents[3] / "supabase" / "migrations"

_START_TIMEOUT_SECONDS = 120

Params = Sequence[Any] | Mapping[str, Any] | None
Query = LiteralString | sql.SQL | sql.Composed


def _helper_python() -> Path:
    scripts = "Scripts/python.exe" if sys.platform == "win32" else "bin/python"
    return SERVER_DIR / ".venv" / scripts


def _read_uri(process: subprocess.Popen[str]) -> str:
    lines: queue.Queue[str] = queue.Queue()

    def pump() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            lines.put(line)

    threading.Thread(target=pump, daemon=True).start()
    collected: list[str] = []
    for _ in range(_START_TIMEOUT_SECONDS):
        try:
            line = lines.get(timeout=1)
        except queue.Empty:
            if process.poll() is not None:
                break
            continue
        collected.append(line.rstrip())
        if line.startswith("URI "):
            return line.removeprefix("URI ").strip()
    raise RuntimeError("The test database did not start:\n" + "\n".join(collected))


class Admin:
    """One long-lived, autocommit, superuser connection for test setup and assertions."""

    def __init__(self, dsn: str) -> None:
        self._connection = psycopg.Connection[DictRow].connect(
            dsn, autocommit=True, row_factory=dict_row, prepare_threshold=None
        )
        self._acting = False

    def close(self) -> None:
        self._connection.close()

    def _guard(self) -> None:
        if self._acting:
            raise RuntimeError("Admin queries are not allowed inside acting_as(); do them first.")

    def execute(self, query: Query, params: Params = None) -> psycopg.Cursor[DictRow]:
        self._guard()
        return self._connection.execute(query, params)

    def fetchall(self, query: Query, params: Params = None) -> list[DictRow]:
        return self.execute(query, params).fetchall()

    def fetchone(self, query: Query, params: Params = None) -> DictRow | None:
        return self.execute(query, params).fetchone()

    def scalar(self, query: Query, params: Params = None) -> Any:
        """The first column of the first row (None if there is no row)."""
        row = self.fetchone(query, params)
        return next(iter(row.values())) if row else None

    def run_script(self, script: str) -> None:
        """Run a multi-statement SQL file (the stub, a migration). Trusted content only."""
        self._guard()
        self._connection.execute(cast(LiteralString, script))

    @contextmanager
    def acting_as(
        self, role: str, user_id: uuid.UUID | None = None
    ) -> Generator[psycopg.Connection[DictRow]]:
        """A transaction acting as a database role, the way PostgREST and our API do.

        ``role`` is ``authenticated`` or ``anon``; for ``authenticated`` pass the user's id so
        that ``auth.uid()`` resolves in policies. Always rolled back, so nothing persists.
        """
        self._guard()
        claims = {"sub": str(user_id), "role": role} if user_id else {"role": role}
        self._acting = True
        try:
            with self._connection.transaction(force_rollback=True):
                self._connection.execute(
                    "select set_config('role', %s, true),"
                    " set_config('request.jwt.claims', %s, true)",
                    (role, json.dumps(claims)),
                )
                yield self._connection
        finally:
            self._acting = False


_admins: dict[str, Admin] = {}


def admin(dsn: str) -> Admin:
    """The shared admin connection for this database (created on first use)."""
    if dsn not in _admins:
        _admins[dsn] = Admin(dsn)
    return _admins[dsn]


def _close_admins() -> None:
    while _admins:
        _, connection = _admins.popitem()
        connection.close()


def _bootstrap(dsn: str) -> None:
    connection = admin(dsn)
    connection.run_script(STUB_SQL.read_text(encoding="utf-8"))
    for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
        connection.run_script(migration.read_text(encoding="utf-8"))


@contextmanager
def running_database() -> Generator[str]:
    """Provide a database with the Supabase stub and every migration applied; yield its DSN."""
    external = os.environ.get("TEST_DATABASE_URL")
    if external:
        try:
            _bootstrap(external)
            yield external
        finally:
            _close_admins()
        return

    python = _helper_python()
    if not python.exists():
        raise RuntimeError(
            "The test database is not installed. "
            "Run: uv sync --directory services/api/tests/pg_server"
        )

    process = subprocess.Popen(  # noqa: S603 - fixed command, no user input
        [str(python), "serve.py"],
        cwd=SERVER_DIR,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        dsn = _read_uri(process)
        _bootstrap(dsn)
        yield dsn
    finally:
        _close_admins()
        # Closing stdin tells the helper to stop PostgreSQL and exit.
        if process.stdin is not None:
            process.stdin.close()
        try:
            process.wait(timeout=60)
        except subprocess.TimeoutExpired:
            process.kill()


def create_auth_user(
    dsn: str, *, email: str | None = None, display_name: str | None = None
) -> uuid.UUID:
    """Insert into auth.users as Supabase Auth does on sign-up (the trigger adds a profile)."""
    user_id = uuid.uuid4()
    metadata = {"display_name": display_name} if display_name is not None else {}
    admin(dsn).execute(
        "insert into auth.users (id, email, raw_user_meta_data) values (%s, %s, %s)",
        (user_id, email or f"{user_id}@example.test", Jsonb(metadata)),
    )
    return user_id
