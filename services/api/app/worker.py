"""The background worker process.

Run it next to the API (it reads the same ``.env``)::

    uv run python -m app.worker

It claims queued jobs from PostgreSQL (roadmap generation today), runs them, and keeps going until
interrupted; Ctrl+C lets a job that is running finish first. On Windows it needs a selector event
loop, which ``main`` selects, because psycopg's async mode rejects the default proactor loop.
"""

import asyncio
import os
import signal
import socket
import sys
import uuid
from types import FrameType

import httpx2
import structlog

from app.ai.factory import build_provider
from app.ai.provider import LLMNotConfigured, LLMProvider
from app.core.config import EX_CONFIG, Settings, load_settings_or_exit
from app.core.db import Database
from app.core.logging import configure_logging
from app.documents.storage import build_document_files
from app.jobs.runtime import WorkerEnv
from app.jobs.worker import Worker

log = structlog.get_logger("app.worker")


def _worker_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"


async def run_worker(settings: Settings, stop: asyncio.Event) -> None:
    database = Database.from_settings(settings)
    await database.open(wait=True)
    try:
        async with httpx2.AsyncClient() as client:
            provider: LLMProvider | None
            try:
                provider = build_provider(settings, client)
            except LLMNotConfigured:
                provider = None
                log.warning(
                    "worker.ai_not_configured",
                    hint="Set LLM_PROVIDER (and GEMINI_API_KEY) or AI jobs will fail.",
                )
            env = WorkerEnv(
                database=database,
                settings=settings,
                worker_id=_worker_id(),
                provider=provider,
                files=build_document_files(settings, client),
            )
            await Worker(env).run(stop)
    finally:
        await database.close()


def _install_signal_handlers(loop: asyncio.AbstractEventLoop, stop: asyncio.Event) -> None:
    def request_stop(_signum: int, _frame: FrameType | None) -> None:
        loop.call_soon_threadsafe(stop.set)

    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):  # SIGBREAK exists on Windows only
        number = getattr(signal, name, None)
        if number is not None:
            signal.signal(number, request_stop)


async def _main(settings: Settings) -> None:
    stop = asyncio.Event()
    _install_signal_handlers(asyncio.get_running_loop(), stop)
    await run_worker(settings, stop)


def main() -> None:
    settings = load_settings_or_exit()
    configure_logging(settings.log_level, json_logs=settings.json_logs)
    if settings.database_url is None:
        sys.stderr.write("DATABASE_URL must be set for the worker.\n")
        raise SystemExit(EX_CONFIG)
    asyncio.run(_main(settings), loop_factory=asyncio.SelectorEventLoop)


if __name__ == "__main__":
    main()
