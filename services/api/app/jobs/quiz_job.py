"""Running one quiz job: load the topic and its lesson, write the quiz, validate it, store it.

Stages (``generation_jobs.stage`` / ``progress``): loading 5 -> writing 20 -> validated 75 ->
saving 90 -> done 100. The validated quiz is checkpointed before saving, so if storing it fails and
the job is retried, the (paid) model call is not repeated. How a job *ends* is decided in
``runner.py``.
"""

import re

import structlog

from app.ai.calls import CallRecord
from app.ai.provider import LLMNotConfigured
from app.ai.quiz.context import build_context
from app.ai.quiz.writer import write_quiz
from app.jobs import lesson_store, queue, quiz_store, store
from app.jobs.errors import JobFailure, LeaseLost
from app.jobs.queue import Job
from app.jobs.runtime import Lease, WorkerEnv, as_uuid, set_stage

log = structlog.get_logger("app.jobs")

_OBJECTIVE_ID = re.compile(r"^[A-Za-z0-9_-]{1,20}$")


def _clamp(value: object, low: int, high: int, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return max(low, min(high, value))


async def run_quiz(env: WorkerEnv, job: Job, lease: Lease) -> None:
    await set_stage(env, job, "loading", 5)
    lease.check()
    if job.item_id is None:  # the database forbids this; stay safe if it ever happens
        raise JobFailure("TOPIC_UNAVAILABLE", "This quiz job has no topic.")
    async with env.database.system_session() as connection:
        goal = await store.load_goal(connection, job.user_id, job.goal_id)
        facts = await lesson_store.load_topic(connection, job.user_id, job.item_id)
    if goal is None or facts is None:
        raise JobFailure("TOPIC_UNAVAILABLE", "This topic no longer exists.")
    if goal.status == "archived":
        raise JobFailure("GOAL_UNAVAILABLE", "This goal is archived. Restore it to take quizzes.")
    if facts.kind == "revision":
        raise JobFailure("TOPIC_UNAVAILABLE", "Revision sessions don't have quizzes.")

    purpose = "practice" if job.request.get("purpose") == "practice" else "check"
    raw_focus: object = job.request.get("focus_objective_ids")
    candidates: list[object] = list(raw_focus) if isinstance(raw_focus, list) else []  # pyright: ignore[reportUnknownArgumentType]
    focus = [item for item in candidates if isinstance(item, str) and _OBJECTIVE_ID.match(item)][:6]
    count = _clamp(job.request.get("question_count"), 3, 10, env.settings.quiz_question_count)
    max_short = _clamp(job.request.get("max_short_answers"), 0, 2, env.settings.quiz_short_answers)

    lesson_id = as_uuid(job.request.get("lesson_id"))
    if lesson_id is None:
        raise JobFailure("LESSON_REQUIRED", "A quiz is written from a lesson, and none was given.")
    async with env.database.system_session() as connection:
        lesson = await lesson_store.load_lesson(connection, job.user_id, job.item_id, lesson_id)
    if lesson is None:
        raise JobFailure("LESSON_REQUIRED", "The lesson for this quiz is no longer available.")

    async with env.database.system_session() as connection:
        objectives = await quiz_store.load_objectives(connection, job.user_id, job.item_id)
    # A request is only a hint: it can name nothing the topic doesn't have (the API sets it, but a
    # row inserted some other way must not be able to aim a quiz at an arbitrary id).
    known = {objective.id for objective in objectives}
    focus = [item for item in focus if item in known]

    if job.checkpoint:
        quiz, meta = quiz_store.restore_checkpoint(job.checkpoint)
    else:
        if env.provider is None:
            raise JobFailure("AI_NOT_CONFIGURED", LLMNotConfigured.user_message)
        await set_stage(env, job, "writing", 20)
        async with env.database.system_session() as connection:
            previous = await quiz_store.load_previous_prompts(connection, job.user_id, job.item_id)
        context = build_context(
            goal,
            topic_title=facts.title,
            topic_description=facts.description,
            objectives=objectives,
            lesson=lesson,
            language=facts.language,
            purpose=purpose,
            focus_objective_ids=tuple(focus),
            question_count=count,
            max_short_answers=max_short,
            previous_prompts=previous,
            shuffle_seed=str(job.id),
        )

        async def observe(record: CallRecord) -> None:
            async with env.database.system_session() as connection:
                await queue.record_usage(connection, job, record)

        outcome = await write_quiz(env.provider, context, observer=observe)
        lease.check()
        quiz = outcome.quiz
        meta = quiz_store.QuizMeta(
            prompt_version=outcome.prompt_version,
            provider=outcome.provider,
            model_id=outcome.model_id,
            synthetic=outcome.synthetic,
        )
        async with env.database.system_session() as connection:
            if not await queue.save_checkpoint(
                connection, job.id, env.worker_id, quiz_store.checkpoint_of(quiz, meta)
            ):
                raise LeaseLost
        await set_stage(env, job, "validated", 75)

    lease.check()
    await set_stage(env, job, "saving", 90)
    async with env.database.system_session() as connection:
        saved = await quiz_store.save_quiz(
            connection,
            job,
            env.worker_id,
            roadmap_id=facts.roadmap_id,
            item_id=job.item_id,
            lesson_id=lesson_id,
            quiz=quiz,
            meta=meta,
            purpose=purpose,
            focus_objective_ids=focus,
        )
    log.info(
        "job.completed",
        job_id=str(job.id),
        quiz_id=str(saved.id),
        questions=len(quiz.questions),
        purpose=purpose,
        synthetic=meta.synthetic,
    )
