"""The worker loop: claim a job, run it, repeat; and recover jobs whose worker vanished."""

import asyncio
import random
from contextlib import suppress

import structlog

from app.jobs import queue
from app.jobs.roadmap_job import WorkerEnv, process_job

log = structlog.get_logger("app.worker")


class Worker:
    def __init__(self, env: WorkerEnv) -> None:
        self.env = env

    async def run_once(self) -> bool:
        """Claim and fully process one job. Returns False if the queue had nothing runnable."""
        settings = self.env.settings
        async with self.env.database.system_session() as connection:
            job = await queue.claim_next(
                connection,
                worker_id=self.env.worker_id,
                lease_seconds=settings.job_lease_seconds,
                max_attempts=settings.job_max_attempts,
            )
        if job is None:
            return False
        log.info("job.claimed", job_id=str(job.id), job_type=job.job_type, attempt=job.attempts)
        await process_job(self.env, job)
        return True

    async def reap_once(self) -> int:
        """Recover jobs whose lease ran out (their worker died). Returns how many."""
        async with self.env.database.system_session() as connection:
            recovered = await queue.reap_expired(connection)
        for job_id in recovered:
            log.warning("job.recovered", job_id=str(job_id))
        return len(recovered)

    async def run(self, stop: asyncio.Event) -> None:
        """Process jobs until ``stop`` is set; jobs already running are allowed to finish."""
        log.info(
            "worker.started",
            worker_id=self.env.worker_id,
            concurrency=self.env.settings.worker_concurrency,
            ai_configured=self.env.provider is not None,
        )
        tasks = [
            asyncio.create_task(self._consume(stop))
            for _ in range(self.env.settings.worker_concurrency)
        ]
        tasks.append(asyncio.create_task(self._reap(stop)))
        await asyncio.gather(*tasks)
        log.info("worker.stopped", worker_id=self.env.worker_id)

    async def _consume(self, stop: asyncio.Event) -> None:
        poll = self.env.settings.worker_poll_seconds
        while not stop.is_set():
            try:
                processed = await self.run_once()
            except Exception:
                log.exception("worker.loop_error")
                processed = False
            if not processed:
                await _sleep_or_stop(stop, poll * (0.5 + random.random()))  # noqa: S311 - poll jitter

    async def _reap(self, stop: asyncio.Event) -> None:
        interval = max(1.0, self.env.settings.job_lease_seconds / 2)
        while not stop.is_set():
            try:
                await self.reap_once()
            except Exception:
                log.exception("worker.reap_error")
            await _sleep_or_stop(stop, interval)


async def _sleep_or_stop(stop: asyncio.Event, seconds: float) -> None:
    with suppress(TimeoutError):
        await asyncio.wait_for(stop.wait(), timeout=seconds)
