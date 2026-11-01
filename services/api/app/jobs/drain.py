"""A bounded run of the worker, for platforms that start it per message (ADR-052).

``drain`` does what the long-running worker loop does, for a limited time: it recovers jobs whose
lease ran out (their run was cut off), then claims and runs jobs one after another. It starts a new
job only while the time budget lasts, so the job it starts last can still finish before the
platform stops it. ``follow_up`` then asks for the next run: at once if runnable jobs are left, or
when the soonest retry falls due.

Nothing here changes how a job runs: claiming, leases, checkpoints, retries and how a job ends are
the same code the long-running worker uses (``Worker``, ``runner.process_job``).
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog

from app.jobs import queue
from app.jobs.runtime import WorkerEnv
from app.jobs.wake import JobWake
from app.jobs.worker import Worker

log = structlog.get_logger("app.worker")


@dataclass(frozen=True)
class DrainResult:
    processed: int
    recovered: int
    # The budget ran out while jobs may still have been waiting.
    out_of_time: bool


async def drain(
    env: WorkerEnv,
    *,
    budget_seconds: float,
    clock: Callable[[], float] = time.monotonic,
) -> DrainResult:
    worker = Worker(env)
    started = clock()
    recovered = await worker.reap_once()
    processed = 0
    out_of_time = False
    while True:
        if clock() - started >= budget_seconds:
            out_of_time = True
            break
        if not await worker.run_once():
            break
        processed += 1
    log.info(
        "worker.drained",
        worker_id=env.worker_id,
        processed=processed,
        recovered=recovered,
        out_of_time=out_of_time,
    )
    return DrainResult(processed=processed, recovered=recovered, out_of_time=out_of_time)


async def follow_up(
    env: WorkerEnv, wake: JobWake, *, now: Callable[[], datetime] = lambda: datetime.now(UTC)
) -> float | None:
    """Ask for the next run if queued work is left. Returns the delay asked for, or None."""
    async with env.database.system_session() as connection:
        next_at = await queue.next_run_at(connection)
    if next_at is None:
        return None
    delay = max(0.0, (next_at - now()).total_seconds())
    # A retry due later is asked for once, however many runs see it; work due now is asked for
    # every time (an extra run that finds nothing to do ends at once).
    key = f"run-at-{next_at.timestamp():.0f}" if delay > 0 else None
    await wake.wake(delay_seconds=delay, key=key)
    return delay
