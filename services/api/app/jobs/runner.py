"""Running one claimed job to a final state, whatever kind it is.

``process_job`` picks the job's runner, and is the single place that decides how each way of
ending is recorded: finished, cancelled, failed with a learner-safe reason, or put back in the
queue to try again later with exponential backoff while attempts remain.
"""

import structlog

from app.ai.grading.grader import GradingInvalid
from app.ai.lesson.writer import LessonInvalid
from app.ai.provider import LLMError
from app.ai.quiz.writer import QuizInvalid
from app.ai.roadmap.planner import PlanInvalid
from app.jobs import document_store, queue
from app.jobs.document_job import run_document
from app.jobs.errors import JobCancelled, JobFailure, LeaseLost
from app.jobs.grade_job import run_grade
from app.jobs.lesson_job import run_lesson
from app.jobs.queue import Job
from app.jobs.quiz_job import run_quiz
from app.jobs.roadmap_job import run_roadmap
from app.jobs.runtime import Lease, WorkerEnv, backoff_seconds

log = structlog.get_logger("app.jobs")


async def process_job(env: WorkerEnv, job: Job) -> None:
    """Run a claimed job to a final state (or back into the queue). Never raises for job errors."""
    async with Lease(env, job) as lease:
        try:
            if job.job_type == "lesson":
                await run_lesson(env, job, lease)
            elif job.job_type == "quiz":
                await run_quiz(env, job, lease)
            elif job.job_type == "grade":
                await run_grade(env, job, lease)
            elif job.job_type == "document":
                await run_document(env, job, lease)
            else:
                await run_roadmap(env, job, lease)
        except LeaseLost:
            log.warning("job.lease_lost", job_id=str(job.id))
        except JobCancelled:
            async with env.database.system_session() as connection:
                cancelled = await queue.mark_cancelled(connection, job.id, env.worker_id)
                if cancelled and job.document_id is not None:
                    await document_store.mark_failed(
                        connection,
                        job.user_id,
                        job.document_id,
                        code="JOB_CANCELLED",
                        message="Processing was stopped. Process it again to retry.",
                        scrub_job=job.id,
                    )
            log.info("job.cancelled", job_id=str(job.id))
        except JobFailure as failure:
            await _end(env, job, failure.code, failure.message, retryable=failure.retryable)
        except (PlanInvalid, LessonInvalid, QuizInvalid, GradingInvalid) as invalid:
            log.info(
                "job.output_invalid",
                job_id=str(job.id),
                job_type=job.job_type,
                violations=sorted({v.code for v in invalid.violations}),
            )
            await _end(env, job, invalid.code, invalid.user_message, retryable=False)
        except LLMError as error:
            log.warning(
                "job.model_error",
                job_id=str(job.id),
                code=error.code,
                retryable=error.retryable,
                detail=error.detail,
            )
            await _end(
                env,
                job,
                error.code,
                error.user_message,
                retryable=error.retryable,
                retry_after=error.retry_after,
            )
        except Exception:
            log.exception("job.unexpected_error", job_id=str(job.id))
            await _end(
                env, job, "INTERNAL_ERROR", "Something went wrong on our side.", retryable=True
            )


async def _end(
    env: WorkerEnv,
    job: Job,
    code: str,
    message: str,
    *,
    retryable: bool,
    retry_after: float | None = None,
) -> None:
    """Retry later if the failure is transient and attempts remain; otherwise fail for good."""
    async with env.database.system_session() as connection:
        if retryable and job.attempts < job.max_attempts:
            delay = backoff_seconds(
                job.attempts,
                env.settings.job_retry_base_seconds,
                jitter=env.random(),
                retry_after=retry_after,
            )
            await queue.retry_later(
                connection,
                job.id,
                env.worker_id,
                code=code,
                message=f"{message} Trying again shortly.",
                delay_seconds=delay,
            )
            log.info("job.retry_scheduled", job_id=str(job.id), code=code, in_seconds=round(delay))
            return
        suffix = " Please try again in a few minutes." if retryable else ""
        failed = await queue.fail(
            connection, job.id, env.worker_id, code=code, message=message + suffix
        )
        if failed and job.document_id is not None:
            # A document must never wait for a job that has ended; and the signed link goes too.
            await document_store.mark_failed(
                connection,
                job.user_id,
                job.document_id,
                code=code,
                message=message + suffix,
                scrub_job=job.id,
            )
        log.info("job.failed", job_id=str(job.id), code=code)
