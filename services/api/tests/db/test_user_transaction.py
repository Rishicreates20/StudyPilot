"""The production database access helper (Database.user_transaction), against a real database."""

import asyncio
import uuid
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from pydantic import SecretStr

from app.core.config import AppEnv
from app.core.db import Database
from app.core.security import Principal
from support.database import admin, create_auth_user
from support.settings import IsolatedSettings

pytestmark = pytest.mark.anyio


def principal_for(user_id: uuid.UUID) -> Principal:
    return Principal(
        user_id=user_id,
        email=None,
        claims={"sub": str(user_id), "role": "authenticated", "aud": "authenticated"},
    )


@pytest.fixture(scope="module")
async def database(database_dsn: str) -> AsyncGenerator[Database]:
    """A pool with ONE connection, so every user below shares the same physical connection.

    Reuse of a connection by successive users is exactly where a leaked identity would show up.
    """
    settings = IsolatedSettings(
        app_env=AppEnv.TEST,
        database_url=SecretStr(database_dsn),
        db_pool_min_size=1,
        db_pool_max_size=1,
    )
    db = Database.from_settings(settings)
    await db.open(wait=True)
    try:
        yield db
    finally:
        await db.close()


async def test_inside_the_transaction_the_session_is_the_verified_user(
    database: Database, database_dsn: str
) -> None:
    user_id = create_auth_user(database_dsn)

    async with database.user_transaction(principal_for(user_id)) as connection:
        cursor = await connection.execute(
            "select current_user as role, auth.uid() as uid,"
            " (current_setting('request.jwt.claims')::jsonb ->> 'role') as claim_role"
        )
        row = await cursor.fetchone()

    assert row == {"role": "authenticated", "uid": user_id, "claim_role": "authenticated"}


async def test_the_connection_is_unrestricted_again_after_the_transaction(
    database: Database, database_dsn: str
) -> None:
    """A pooled connection must never carry one user's identity into the next request."""
    user_id = create_auth_user(database_dsn)
    async with database.user_transaction(principal_for(user_id)) as connection:
        await connection.execute("select 1")

    # Reaching into the pool is the point of this test: it must come back unrestricted.
    pool: Any = database._pool  # pyright: ignore[reportPrivateUsage]
    async with pool.connection() as raw:
        cursor = await raw.execute(
            "select current_user as role,"
            " nullif(current_setting('request.jwt.claims', true), '') as claims"
        )
        row = await cursor.fetchone()

    assert row["role"] != "authenticated"
    assert row["claims"] is None


async def test_successive_users_on_the_same_connection_never_see_each_others_identity(
    database: Database, database_dsn: str
) -> None:
    users = [create_auth_user(database_dsn) for _ in range(12)]
    seen: list[uuid.UUID] = []

    for user_id in [*users, *reversed(users)]:
        async with database.user_transaction(principal_for(user_id)) as connection:
            row = await (await connection.execute("select auth.uid() as uid")).fetchone()
            assert row is not None
            seen.append(row["uid"])

    assert seen == [*users, *reversed(users)]


async def test_a_query_without_a_user_filter_returns_only_the_callers_rows(
    database: Database, database_dsn: str
) -> None:
    alice = create_auth_user(database_dsn)
    bob = create_auth_user(database_dsn)
    admin(database_dsn).execute(
        "insert into public.learning_goals (user_id, title) values (%s, 'A'), (%s, 'B')",
        (alice, bob),
    )

    async with database.user_transaction(principal_for(alice)) as connection:
        cursor = await connection.execute("select user_id from public.learning_goals")
        rows = await cursor.fetchall()

    assert rows == [{"user_id": alice}]


async def test_work_is_rolled_back_when_the_block_raises(
    database: Database, database_dsn: str
) -> None:
    user_id = create_auth_user(database_dsn)

    with pytest.raises(RuntimeError, match="boom"):
        async with database.user_transaction(principal_for(user_id)) as connection:
            await connection.execute(
                "insert into public.learning_goals (user_id, title) values (%s, 'doomed')",
                (user_id,),
            )
            raise RuntimeError("boom")

    assert (
        admin(database_dsn).scalar(
            "select count(*) from public.learning_goals where user_id = %s", (user_id,)
        )
        == 0
    )


async def test_work_is_committed_when_the_block_succeeds(
    database: Database, database_dsn: str
) -> None:
    user_id = create_auth_user(database_dsn)

    async with database.user_transaction(principal_for(user_id)) as connection:
        await connection.execute(
            "insert into public.learning_goals (user_id, title) values (%s, 'kept')", (user_id,)
        )

    assert (
        admin(database_dsn).scalar(
            "select count(*) from public.learning_goals where user_id = %s", (user_id,)
        )
        == 1
    )


async def test_ping_reports_a_reachable_database(database: Database) -> None:
    assert await database.ping() is True


async def test_concurrent_users_never_see_each_others_identity(database_dsn: str) -> None:
    settings = IsolatedSettings(
        app_env=AppEnv.TEST,
        database_url=SecretStr(database_dsn),
        db_pool_min_size=4,
        db_pool_max_size=4,
    )
    concurrent = Database.from_settings(settings)
    await concurrent.open(wait=True)
    users = [create_auth_user(database_dsn) for _ in range(8)]

    async def whoami(user_id: uuid.UUID) -> uuid.UUID:
        async with concurrent.user_transaction(principal_for(user_id)) as connection:
            await asyncio.sleep(0.02)  # force the transactions to overlap
            row = await (await connection.execute("select auth.uid() as uid")).fetchone()
            assert row is not None
            return row["uid"]

    try:
        results = await asyncio.gather(*(whoami(user_id) for user_id in users * 4))
    finally:
        await concurrent.close()

    assert results == users * 4
