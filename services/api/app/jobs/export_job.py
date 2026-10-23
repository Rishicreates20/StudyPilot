"""Running one export job: load the source, render the file, upload it, mark the export ready.

Stages (``generation_jobs.stage`` / ``progress``): loading 10 -> rendering 35 -> uploading 70 ->
saving 90 -> done 100. No model is called: rendering is local and deterministic, so a retried job
simply renders again. Rendering is CPU-bound and runs in a thread so the worker's lease keeps
beating. The file is uploaded through the one-object upload capability the API made with the
learner's token; a retry uploads to the same object again (upsert), so no second file is left.

How a job *ends* (retries, failures, cancellation) is decided in ``runner.py``.
"""

import asyncio

import structlog

from app.documents.storage import StorageError
from app.exports.files import object_path
from app.exports.model import LessonSource, RoadmapSource
from app.exports.render import UnsupportedExport, render
from app.jobs import export_store, queue
from app.jobs.errors import JobFailure, LeaseLost
from app.jobs.queue import Job
from app.jobs.runtime import Lease, WorkerEnv, set_stage

log = structlog.get_logger("app.jobs")

# Storage answers that mean the upload capability is no good any more (signed upload links last
# two hours): asking for the export again makes a fresh one.
_LINK_REFUSED = {"STORAGE_FORBIDDEN", "STORAGE_REJECTED"}


async def run_export(env: WorkerEnv, job: Job, lease: Lease) -> None:
    await set_stage(env, job, "loading", 10)
    lease.check()
    if job.export_id is None:  # the database forbids this; stay safe if it ever happens
        raise JobFailure("EXPORT_MISSING", "This export job has no export.")
    async with env.database.system_session() as connection:
        task = await export_store.load_task(connection, job.user_id, job.export_id)
        if task is None:
            raise JobFailure("EXPORT_MISSING", "This export no longer exists.")
        if task.ready_at is not None:
            # Already made (a job that completed after this one was queued): nothing to do.
            if not await queue.complete(connection, job.id, env.worker_id):
                raise LeaseLost
            return
        source: LessonSource | RoadmapSource | None
        if task.lesson_id is not None:
            source = await export_store.lesson_source(
                connection, job.user_id, task.lesson_id, task.goal_title
            )
        elif task.roadmap_id is not None:
            source = await export_store.roadmap_source(
                connection, job.user_id, task.roadmap_id, task.goal_title
            )
        else:
            source = None
    if source is None:
        raise JobFailure("EXPORT_SOURCE_MISSING", "The lesson or roadmap no longer exists.")

    await set_stage(env, job, "rendering", 35)
    lease.check()
    try:
        rendered = await asyncio.to_thread(render, task.format, source)
    except UnsupportedExport:
        raise JobFailure(
            "EXPORT_FORMAT_UNSUPPORTED", "This kind of file can't be made from this source."
        ) from None

    await set_stage(env, job, "uploading", 70)
    lease.check()
    if env.export_files is None:
        raise JobFailure(
            "STORAGE_NOT_CONFIGURED", "File storage isn't set up on this server.", retryable=False
        )
    if not task.upload_token:
        raise JobFailure(
            "EXPORT_LINK_MISSING", "This export can't be stored. Ask for the export again."
        )
    path = object_path(job.user_id, task.id, task.format)
    try:
        await env.export_files.upload(task.upload_token, rendered.data, rendered.content_type)
    except StorageError as problem:
        if problem.retryable:
            raise JobFailure(problem.code, problem.message, retryable=True) from None
        if problem.code == "FILE_TOO_LARGE":
            raise JobFailure(
                "EXPORT_TOO_LARGE", "This file is too large to store. Try a shorter export."
            ) from None
        if problem.code in _LINK_REFUSED:
            raise JobFailure(
                "EXPORT_LINK_EXPIRED",
                "The link for storing this file has expired. Ask for the export again.",
            ) from None
        raise JobFailure(problem.code, problem.message) from None

    await set_stage(env, job, "saving", 90)
    lease.check()
    async with env.database.system_session() as connection:
        saved = await export_store.save_file(
            connection, job.user_id, task.id, storage_path=path, rendered=rendered
        )
        if not await queue.complete(connection, job.id, env.worker_id):
            raise LeaseLost  # rolls the whole transaction back
    log.info(
        "export.ready",
        job_id=str(job.id),
        export_id=str(task.id),
        format=task.format,
        bytes=len(rendered.data),
        pages=rendered.page_count,
        unsupported=rendered.unsupported_characters,
        newly_saved=saved,
    )
