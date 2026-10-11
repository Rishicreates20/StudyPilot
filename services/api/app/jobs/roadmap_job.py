"""Running one roadmap-generation job: load, plan, validate, store.

Stages (``generation_jobs.stage`` / ``progress``): loading 5 -> planning 20 -> validated 70 ->
saving 85 -> done 100. The validated plan is checkpointed before saving, so if storing it fails
and the job is retried, the (paid) model call is not repeated. Between stages the job checks that
it still owns its lease and that the learner has not cancelled.

How a job *ends* (retries, failures, cancellation) is decided in ``runner.py``.
"""

import structlog

from app.ai.calls import CallRecord
from app.ai.provider import LLMNotConfigured
from app.ai.roadmap.context import build_context, readiness_problems
from app.ai.roadmap.planner import plan_roadmap
from app.jobs import queue, store
from app.jobs.errors import JobFailure, LeaseLost
from app.jobs.queue import Job
from app.jobs.runtime import Lease, WorkerEnv, as_uuid, set_stage

log = structlog.get_logger("app.jobs")

_MAX_FEEDBACK_CHARS = 500


async def run_roadmap(env: WorkerEnv, job: Job, lease: Lease) -> None:
    await set_stage(env, job, "loading", 5)
    lease.check()
    async with env.database.system_session() as connection:
        goal = await store.load_goal(connection, job.user_id, job.goal_id)
    if goal is None:
        raise JobFailure("GOAL_UNAVAILABLE", "This goal no longer exists.")
    if goal.status == "archived":
        raise JobFailure(
            "GOAL_UNAVAILABLE", "This goal is archived. Restore it to generate a roadmap."
        )

    raw_feedback = job.request.get("feedback")
    feedback = (
        raw_feedback.strip()[:_MAX_FEEDBACK_CHARS] or None
        if isinstance(raw_feedback, str)
        else None
    )
    based_on = as_uuid(job.request.get("base_roadmap_id"))
    if based_on is not None:
        async with env.database.system_session() as connection:
            based_on = await store.verify_base(connection, job.user_id, job.goal_id, based_on)

    if job.checkpoint:
        plan, meta = store.restore_checkpoint(job.checkpoint)
    else:
        problems = readiness_problems(goal, env.today())
        if problems:
            raise JobFailure("GOAL_NOT_PLANNABLE", problems[0])
        if env.provider is None:
            raise JobFailure("AI_NOT_CONFIGURED", LLMNotConfigured.user_message)
        await set_stage(env, job, "planning", 20)

        outline = None
        if feedback and based_on is not None:
            async with env.database.system_session() as connection:
                outline = await store.load_outline(connection, job.user_id, based_on)
        context = build_context(
            goal, today=env.today(), feedback=feedback, previous_outline=outline
        )

        async def observe(record: CallRecord) -> None:
            async with env.database.system_session() as connection:
                await queue.record_usage(connection, job, record)

        outcome = await plan_roadmap(env.provider, context, observer=observe)
        lease.check()
        plan = outcome.plan
        meta = store.PlanMeta(
            prompt_version=outcome.prompt_version,
            provider=outcome.provider,
            model_id=outcome.model_id,
            synthetic=outcome.synthetic,
            total_minutes=outcome.metrics.total_minutes,
            total_days=outcome.metrics.total_days,
            topic_count=outcome.metrics.topic_count,
        )
        async with env.database.system_session() as connection:
            if not await queue.save_checkpoint(
                connection, job.id, env.worker_id, store.checkpoint_of(plan, meta)
            ):
                raise LeaseLost
        await set_stage(env, job, "validated", 70)

    lease.check()
    await set_stage(env, job, "saving", 85)
    async with env.database.system_session() as connection:
        saved = await store.save_roadmap(
            connection,
            job,
            env.worker_id,
            plan=plan,
            meta=meta,
            goal=goal,
            feedback=feedback,
            based_on=based_on,
        )
    log.info(
        "job.completed",
        job_id=str(job.id),
        roadmap_id=str(saved.id),
        version=saved.version,
        topics=meta.topic_count,
        synthetic=meta.synthetic,
    )
