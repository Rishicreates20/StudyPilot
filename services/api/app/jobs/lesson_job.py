"""Running one lesson job: load the topic, write the lesson, validate it, store it.

Stages (``generation_jobs.stage`` / ``progress``): loading 5 -> writing 20 -> validated 75 ->
saving 90 -> done 100. The validated lesson is checkpointed before saving, so if storing it fails
and the job is retried, the (paid) model call is not repeated. Between stages the job checks that
it still owns its lease and that the learner has not cancelled.

How a job *ends* (retries, failures, cancellation) is decided in ``runner.py``.
"""

from typing import get_args

import structlog

from app.ai.calls import CallRecord
from app.ai.lesson.context import build_context
from app.ai.lesson.schema import Adjust
from app.ai.lesson.writer import write_lesson
from app.ai.provider import LLMNotConfigured
from app.jobs import lesson_store, queue, store
from app.jobs.errors import JobFailure, LeaseLost
from app.jobs.queue import Job
from app.jobs.runtime import Lease, WorkerEnv, as_uuid, set_stage

log = structlog.get_logger("app.jobs")

MAX_LESSON_FEEDBACK_CHARS = 300


def _adjust_of(value: object) -> Adjust | None:
    """The requested adjustment if it is one we know; a job's request is data (anything goes)."""
    for option in get_args(Adjust):
        if value == option:
            return option
    return None


async def run_lesson(env: WorkerEnv, job: Job, lease: Lease) -> None:
    await set_stage(env, job, "loading", 5)
    lease.check()
    if job.item_id is None:  # the database forbids this; stay safe if it ever happens
        raise JobFailure("TOPIC_UNAVAILABLE", "This lesson job has no topic.")
    async with env.database.system_session() as connection:
        goal = await store.load_goal(connection, job.user_id, job.goal_id)
        facts = await lesson_store.load_topic(connection, job.user_id, job.item_id)
    if goal is None or facts is None:
        raise JobFailure("TOPIC_UNAVAILABLE", "This topic no longer exists.")
    if goal.status == "archived":
        raise JobFailure(
            "GOAL_UNAVAILABLE", "This goal is archived. Restore it to generate lessons."
        )
    if facts.kind == "revision":
        raise JobFailure("TOPIC_UNAVAILABLE", "Revision sessions don't have lessons.")

    adjust = _adjust_of(job.request.get("adjust"))
    raw_feedback = job.request.get("feedback")
    feedback = (
        raw_feedback.strip()[:MAX_LESSON_FEEDBACK_CHARS] or None
        if isinstance(raw_feedback, str)
        else None
    )
    based_on = as_uuid(job.request.get("base_lesson_id"))
    previous = None
    if based_on is not None:
        async with env.database.system_session() as connection:
            previous = await lesson_store.load_lesson(
                connection, job.user_id, job.item_id, based_on
            )
        if previous is None:
            based_on = None

    if job.checkpoint:
        lesson, meta = lesson_store.restore_checkpoint(job.checkpoint)
    else:
        if env.provider is None:
            raise JobFailure("AI_NOT_CONFIGURED", LLMNotConfigured.user_message)
        await set_stage(env, job, "writing", 20)
        context = build_context(
            goal,
            facts,
            adjust=adjust,
            feedback=feedback,
            previous_lesson=previous if (adjust or feedback) else None,
        )

        async def observe(record: CallRecord) -> None:
            async with env.database.system_session() as connection:
                await queue.record_usage(connection, job, record)

        outcome = await write_lesson(env.provider, context, observer=observe)
        lease.check()
        lesson = outcome.lesson
        meta = lesson_store.LessonMeta(
            prompt_version=outcome.prompt_version,
            provider=outcome.provider,
            model_id=outcome.model_id,
            synthetic=outcome.synthetic,
        )
        async with env.database.system_session() as connection:
            if not await queue.save_checkpoint(
                connection, job.id, env.worker_id, lesson_store.checkpoint_of(lesson, meta)
            ):
                raise LeaseLost
        await set_stage(env, job, "validated", 75)

    lease.check()
    await set_stage(env, job, "saving", 90)
    async with env.database.system_session() as connection:
        saved = await lesson_store.save_lesson(
            connection,
            job,
            env.worker_id,
            facts=facts,
            lesson=lesson,
            meta=meta,
            adjust=adjust,
            feedback=feedback,
            based_on=based_on,
        )
    log.info(
        "job.completed",
        job_id=str(job.id),
        lesson_id=str(saved.id),
        version=saved.version,
        sections=len(lesson.sections),
        synthetic=meta.synthetic,
    )
