"""Database access: a connection pool and the only way user-facing code obtains a connection.

The safe access pattern
-----------------------
The API connects to PostgreSQL with a powerful login role (Supabase's ``postgres``), which bypasses
Row Level Security. User-facing code therefore NEVER receives a raw pooled connection. It gets a
``UserConnection`` from :meth:`Database.user_transaction`, which, inside a single transaction:

1. drops privileges to the ``authenticated`` role (``set_config('role', ...)`` is transaction
   scoped, so the pooled connection returns to its normal state automatically), and
2. sets ``request.jwt.claims`` to the *verified* claims, so ``auth.uid()`` in policies resolves to
   the verified caller.

From that point PostgreSQL itself enforces ownership: a query that forgets its ``WHERE user_id``
returns no other user's rows. Repositories still filter by user explicitly (defence in depth).

Server-side prepared statements are disabled (``prepare_threshold=None``) so the same code works
behind Supabase's transaction-mode pooler as well as a direct or session-mode connection.
"""

import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any, NewType, cast

import structlog
from psycopg import AsyncConnection
from psycopg.rows import DictRow, dict_row
from psycopg_pool import AsyncConnectionPool

from app.core.config import Settings
from app.core.security import Principal

log = structlog.get_logger("app.db")

# A connection already restricted to the caller's identity. Repository functions accept only this
# type, so handing them an unrestricted connection is a type error.
UserConnection = NewType("UserConnection", AsyncConnection[DictRow])

_PING_TIMEOUT_SECONDS = 2.0


class Database:
    def __init__(self, pool: AsyncConnectionPool[AsyncConnection[DictRow]]) -> None:
        self._pool = pool

    @classmethod
    def from_settings(cls, settings: Settings) -> Database:
        if settings.database_url is None:
            raise ValueError("DATABASE_URL is not configured")
        kwargs: dict[str, Any] = {"row_factory": dict_row, "prepare_threshold": None}
        pool = AsyncConnectionPool[AsyncConnection[DictRow]](
            conninfo=settings.database_url.get_secret_value(),
            min_size=settings.db_pool_min_size,
            max_size=settings.db_pool_max_size,
            timeout=settings.db_pool_timeout_seconds,
            kwargs=kwargs,
            # Discard connections the server or a pooler closed while they sat idle.
            # psycopg types this helper for tuple rows only; it works with any row factory.
            check=cast(Any, AsyncConnectionPool.check_connection),
            open=False,
            name="studypilot-api",
        )
        return cls(pool)

    async def open(self, *, wait: bool = False, wait_timeout: float = 30.0) -> None:
        """Start the pool.

        The default (``wait=False``) lets the API start even if the database is down; /readyz
        then reports it. Tests pass ``wait=True`` so connections exist before the first query.
        """
        await self._pool.open(wait=wait, timeout=wait_timeout)

    async def close(self) -> None:
        await self._pool.close()

    async def ping(self) -> bool:
        """Readiness check: can a connection be obtained and a trivial query run?"""
        async with self._pool.connection(timeout=_PING_TIMEOUT_SECONDS) as connection:
            await connection.execute("select 1")
        return True

    @asynccontextmanager
    async def user_transaction(self, principal: Principal) -> AsyncGenerator[UserConnection]:
        """One transaction acting as ``principal``. Commits on success, rolls back on error."""
        claims = json.dumps(dict(principal.claims), separators=(",", ":"), default=str)
        async with self._pool.connection() as connection, connection.transaction():
            await connection.execute(
                "select set_config('role', 'authenticated', true),"
                " set_config('request.jwt.claims', %s, true)",
                (claims,),
            )
            yield UserConnection(connection)
