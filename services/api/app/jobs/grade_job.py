"""Running one grading job: mark an attempt's short answers against their rubrics.

Stages: loading 5 -> grading 20 -> validated 75 -> saving 90 -> done 100. The validated marks are
checkpointed before they are applied, so a retry does not pay for the model call twice. Marks only
land on answers that are still pending: a learner's own review, made while the job waited, wins.
The score is added up by code from the rubric points the model marked as met.
"""

from typing import Any

import structlog

from app.ai.calls import CallRecord
from app.ai.grading.grader import MarkedAnswer, grade_short_answers
from app.ai.provider import LLMNotConfigured
from app.grading import marks as grading_marks
from app.grading.finalize import finalize_attempt
from app.jobs import queue
from app.jobs.errors import JobFailure, LeaseLost
from app.jobs.queue import Job
from app.jobs.runtime import Lease, WorkerEnv, set_stage
from app.learning.mastery import MasteryConfig

log = structlog.get_logger("app.jobs")


def _restore(checkpoint: dict[str, Any]) -> tuple[MarkedAnswer, ...]:
    return tuple(
        MarkedAnswer(
            answer_id=str(item["answer_id"]),
            met_point_ids=tuple(str(point) for point in item["met_point_ids"]),
            comment=str(item["comment"]),
        )
        for item in checkpoint["marks"]
    )


async def run_grade(env: WorkerEnv, job: Job, lease: Lease) -> None:
    await set_stage(env, job, "loading", 5)
    lease.check()
    if job.attempt_id is None:  # the database forbids this; stay safe if it ever happens
        raise JobFailure("ATTEMPT_UNAVAILABLE", "This grading job has no attempt.")
    config = MasteryConfig.from_settings(env.settings)

    async with env.database.system_session() as connection:
        language, answers = await grading_marks.load_pending(
            connection, user_id=job.user_id, attempt_id=job.attempt_id
        )
    if not answers:  # everything was marked or reviewed while this job waited
        async with env.database.system_session() as connection:
            await finalize_attempt(
                connection, user_id=job.user_id, attempt_id=job.attempt_id, config=config
            )
            if not await queue.complete(connection, job.id, env.worker_id):
                raise LeaseLost
        return

    if job.checkpoint:
        marks = _restore(job.checkpoint)
    else:
        if env.provider is None:
            raise JobFailure("AI_NOT_CONFIGURED", LLMNotConfigured.user_message)
        await set_stage(env, job, "grading", 20)

        async def observe(record: CallRecord) -> None:
            async with env.database.system_session() as connection:
                await queue.record_usage(connection, job, record)

        outcome = await grade_short_answers(
            env.provider, answers, language=language, observer=observe
        )
        lease.check()
        marks = outcome.marks
        checkpoint = {
            "marks": [
                {
                    "answer_id": m.answer_id,
                    "met_point_ids": list(m.met_point_ids),
                    "comment": m.comment,
                }
                for m in marks
            ]
        }
        async with env.database.system_session() as connection:
            if not await queue.save_checkpoint(connection, job.id, env.worker_id, checkpoint):
                raise LeaseLost
        await set_stage(env, job, "validated", 75)

    lease.check()
    await set_stage(env, job, "saving", 90)
    async with env.database.system_session() as connection:
        await grading_marks.apply_marks(connection, job, env.worker_id, marks, config=config)
    log.info("job.completed", job_id=str(job.id), marked=len(marks))
