"""Building a worker's environment: the database pool, the model provider and file storage.

Shared by the long-running worker process (``app.worker``) and the bounded runs that Vercel Queues
starts (``app.jobs.queue_consumer``), so both run jobs with exactly the same setup.
"""

import os
import socket
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import httpx2
import structlog

from app.ai.factory import build_provider
from app.ai.provider import LLMNotConfigured, LLMProvider
from app.core.config import Settings
from app.core.db import Database
from app.documents.storage import build_document_files
from app.jobs.runtime import WorkerEnv

log = structlog.get_logger("app.worker")


def new_worker_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"


@asynccontextmanager
async def worker_environment(settings: Settings) -> AsyncGenerator[WorkerEnv]:
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
            yield WorkerEnv(
                database=database,
                settings=settings,
                worker_id=new_worker_id(),
                provider=provider,
                files=build_document_files(settings, client),
            )
    finally:
        await database.close()
