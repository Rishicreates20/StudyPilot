"""Helpers for tests that run the real worker against the test PostgreSQL."""

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any

from pydantic import SecretStr

from app.ai.provider import LLMProvider
from app.core.config import AppEnv, Settings
from app.core.db import Database
from app.documents.storage import DocumentFiles
from app.exports.files import ExportFiles
from app.jobs.runtime import WorkerEnv
from support.database import admin, create_auth_user
from support.plans import TODAY
from support.rows import add_goal, add_job
from support.settings import TEST_SUPABASE_URL, IsolatedSettings


def worker_settings(dsn: str, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "app_env": AppEnv.TEST,
        "database_url": SecretStr(dsn),
        "supabase_url": TEST_SUPABASE_URL,
        "db_pool_max_size": 8,
        # No waiting in tests unless a test asks for it.
        "job_retry_base_seconds": 0.0,
        "job_lease_seconds": 30,
        "job_max_attempts": 3,
        **overrides,
    }
    return IsolatedSettings(**values)


def make_env(
    database: Database,
    settings: Settings,
    provider: LLMProvider | None,
    *,
    worker_id: str = "test-worker",
    today: date = TODAY,
    files: DocumentFiles | None = None,
    export_files: ExportFiles | None = None,
    sleep: Callable[[float], Awaitable[None]] | None = None,
) -> WorkerEnv:
    async def instantly(_seconds: float) -> None:
        return None

    return WorkerEnv(
        database=database,
        settings=settings,
        worker_id=worker_id,
        provider=provider,
        files=files,
        export_files=export_files,
        today=lambda: today,
        random=lambda: 0.5,  # jitter factor 1.0: backoff is exactly base * 2^(attempt-1)
        sleep=sleep or instantly,
    )


def seed_job(
    dsn: str, *, request: dict[str, Any] | None = None, **goal_fields: Any
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """A new learner with a goal and a queued roadmap job: (user_id, goal_id, job_id)."""
    from psycopg.types.json import Jsonb

    user = create_auth_user(dsn)
    goal = add_goal(dsn, user, **goal_fields)
    job = add_job(dsn, user, goal, request=Jsonb(request or {}))
    return user, goal, job


def job_state(dsn: str, job_id: uuid.UUID) -> dict[str, Any]:
    row = admin(dsn).fetchone("select * from public.generation_jobs where id = %s", (job_id,))
    assert row is not None
    return dict(row)


def roadmaps_of(dsn: str, goal_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = admin(dsn).fetchall(
        "select * from public.roadmaps where goal_id = %s order by version", (goal_id,)
    )
    return [dict(row) for row in rows]


def items_of(dsn: str, roadmap_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = admin(dsn).fetchall(
        "select * from public.roadmap_items where roadmap_id = %s order by position", (roadmap_id,)
    )
    return [dict(row) for row in rows]


def run_worker_once(
    dsn: str,
    provider: LLMProvider | None = None,
    *,
    files: DocumentFiles | None = None,
    export_files: ExportFiles | None = None,
    **settings: Any,
) -> bool:
    """Process one queued job with the real worker, from a synchronous test.

    Uses the built-in test provider unless one is given; ``files`` is where document jobs read
    uploaded files from and ``export_files`` where export jobs store theirs. Returns False if
    nothing was queued.
    """

    from app.ai.factory import builtin_responder
    from app.ai.fake import FakeProvider
    from app.jobs.worker import Worker

    config = worker_settings(dsn, **settings)

    async def go() -> bool:
        database = Database.from_settings(config)
        await database.open(wait=True)
        try:
            chosen = provider if provider is not None else FakeProvider(builtin_responder)
            env = make_env(database, config, chosen, files=files, export_files=export_files)
            return await Worker(env).run_once()
        finally:
            await database.close()

    return asyncio.run(go(), loop_factory=asyncio.SelectorEventLoop)


def clear_queue(dsn: str) -> None:
    """Cancel every waiting or running job. The test database is shared by the whole session, so
    tests that run the worker start from an empty queue and only ever pick up their own job."""
    admin(dsn).execute(
        "update public.generation_jobs set status = 'cancelled', stage = 'cancelled',"
        " locked_by = null, locked_until = null, finished_at = now()"
        " where status in ('queued', 'running')"
    )
