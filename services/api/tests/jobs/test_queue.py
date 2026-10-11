"""The queue itself: claiming, leases, recovery and the rules for who may write."""

import asyncio
from datetime import timedelta

import pytest

from app.core.db import Database
from app.jobs import queue
from app.jobs.errors import JobCancelled, LeaseLost
from app.jobs.roadmap_job import Lease, backoff_seconds
from app.jobs.worker import Worker
from support.database import admin, create_auth_user
from support.rows import add_goal, add_job
from support.worker import job_state, make_env, seed_job, worker_settings

pytestmark = pytest.mark.anyio


async def claim(database: Database, worker: str = "worker-a", **kwargs: int) -> queue.Job | None:
    async with database.system_session() as connection:
        return await queue.claim_next(
            connection,
            worker_id=worker,
            lease_seconds=kwargs.get("lease_seconds", 30),
            max_attempts=kwargs.get("max_attempts", 3),
        )


# --- Claiming --------------------------------------------------------------------------------


async def test_claiming_locks_the_job_to_one_worker(database: Database, database_dsn: str) -> None:
    _, _, job_id = seed_job(database_dsn)

    job = await claim(database)

    assert job is not None and job.id == job_id
    assert job.attempts == 1
    state = job_state(database_dsn, job_id)
    assert (state["status"], state["stage"], state["locked_by"]) == (
        "running",
        "starting",
        "worker-a",
    )
    assert state["locked_until"] is not None and state["started_at"] is not None


async def test_the_oldest_runnable_job_goes_first(database: Database, database_dsn: str) -> None:
    _, _, first = seed_job(database_dsn)
    _, _, second = seed_job(database_dsn)

    claimed = [await claim(database), await claim(database)]

    assert [job.id for job in claimed if job] == [first, second]
    assert await claim(database) is None


async def test_a_job_scheduled_for_later_is_not_claimed_yet(
    database: Database, database_dsn: str
) -> None:
    _, _, job_id = seed_job(database_dsn)
    admin(database_dsn).execute(
        "update public.generation_jobs set run_at = now() + interval '1 hour' where id = %s",
        (job_id,),
    )

    assert await claim(database) is None


async def test_many_workers_claiming_at_once_never_take_the_same_job(
    database: Database, database_dsn: str
) -> None:
    created = {seed_job(database_dsn)[2] for _ in range(6)}

    claimed = await asyncio.gather(*(claim(database, worker=f"w{n}") for n in range(10)))

    ids = [job.id for job in claimed if job]
    assert len(ids) == len(set(ids)) == 6  # six jobs, six distinct claims, four workers idle
    assert set(ids) == created
    assert claimed.count(None) == 4


async def test_claiming_applies_the_configured_attempt_limit(
    database: Database, database_dsn: str
) -> None:
    _, _, job_id = seed_job(database_dsn)

    job = await claim(database, max_attempts=5)

    assert job is not None and job.max_attempts == 5
    assert job_state(database_dsn, job_id)["max_attempts"] == 5


# --- Only the owner may write ----------------------------------------------------------------


async def test_a_worker_that_lost_its_lease_cannot_change_the_job(
    database: Database, database_dsn: str
) -> None:
    _, _, job_id = seed_job(database_dsn)
    await claim(database, "worker-a")
    admin(database_dsn).execute(
        "update public.generation_jobs set locked_until = now() - interval '1 second'"
        " where id = %s",
        (job_id,),
    )
    async with database.system_session() as connection:
        await queue.reap_expired(connection)
    taken_over = await claim(database, "worker-b")
    assert taken_over is not None and taken_over.attempts == 2

    async with database.system_session() as connection:
        results = [
            await queue.set_stage(connection, job_id, "worker-a", "saving", 90),
            await queue.save_checkpoint(connection, job_id, "worker-a", {"x": 1}),
            await queue.complete(connection, job_id, "worker-a"),
            await queue.fail(connection, job_id, "worker-a", code="X", message="stale"),
            await queue.retry_later(
                connection, job_id, "worker-a", code="X", message="stale", delay_seconds=1
            ),
            await queue.mark_cancelled(connection, job_id, "worker-a"),
            await queue.heartbeat(connection, job_id, "worker-a", lease_seconds=30),
        ]

    assert results == [False, False, False, False, False, False, None]
    state = job_state(database_dsn, job_id)
    assert (state["status"], state["locked_by"], state["stage"]) == (
        "running",
        "worker-b",
        "starting",
    )


async def test_an_owner_can_report_progress_and_finish(
    database: Database, database_dsn: str
) -> None:
    _, _, job_id = seed_job(database_dsn)
    await claim(database)

    async with database.system_session() as connection:
        assert await queue.set_stage(connection, job_id, "worker-a", "planning", 20)
        assert await queue.heartbeat(connection, job_id, "worker-a", lease_seconds=60) is False
    assert (
        job_state(database_dsn, job_id)["stage"],
        job_state(database_dsn, job_id)["progress"],
    ) == (
        "planning",
        20,
    )
    async with database.system_session() as connection:
        assert await queue.complete(connection, job_id, "worker-a")

    state = job_state(database_dsn, job_id)
    assert (state["status"], state["progress"], state["locked_by"]) == ("completed", 100, None)


# --- Recovery --------------------------------------------------------------------------------


def expire_lock(dsn: str, job_id: object) -> None:
    admin(dsn).execute(
        "update public.generation_jobs set locked_until = now() - interval '1 second'"
        " where id = %s",
        (job_id,),
    )


async def reap(database: Database) -> list[object]:
    async with database.system_session() as connection:
        return list(await queue.reap_expired(connection))


async def test_a_job_whose_worker_died_goes_back_in_the_queue(
    database: Database, database_dsn: str
) -> None:
    _, _, job_id = seed_job(database_dsn)
    await claim(database)
    expire_lock(database_dsn, job_id)

    assert await reap(database) == [job_id]

    state = job_state(database_dsn, job_id)
    assert (state["status"], state["stage"], state["locked_by"]) == (
        "queued",
        "waiting_retry",
        None,
    )
    assert state["error_code"] == "WORKER_LOST"
    assert await claim(database, "worker-b") is not None  # and another worker can take it


async def test_a_job_that_keeps_killing_its_worker_is_eventually_failed(
    database: Database, database_dsn: str
) -> None:
    _, _, job_id = seed_job(database_dsn)
    for _ in range(3):
        assert await claim(database, max_attempts=3) is not None
        expire_lock(database_dsn, job_id)
        await reap(database)

    state = job_state(database_dsn, job_id)
    assert (state["status"], state["error_code"], state["attempts"]) == ("failed", "WORKER_LOST", 3)
    assert state["finished_at"] is not None
    assert await claim(database) is None


async def test_a_cancelled_job_whose_worker_died_is_cancelled_not_retried(
    database: Database, database_dsn: str
) -> None:
    _, _, job_id = seed_job(database_dsn)
    await claim(database)
    admin(database_dsn).execute(
        "update public.generation_jobs set cancel_requested = true where id = %s", (job_id,)
    )
    expire_lock(database_dsn, job_id)

    await reap(database)

    state = job_state(database_dsn, job_id)
    assert (state["status"], state["error_code"]) == ("cancelled", None)
    assert state["finished_at"] is not None


async def test_jobs_with_a_live_lease_are_left_alone(database: Database, database_dsn: str) -> None:
    _, _, job_id = seed_job(database_dsn)
    await claim(database, lease_seconds=300)

    assert await reap(database) == []
    assert job_state(database_dsn, job_id)["status"] == "running"


async def test_the_worker_recovers_jobs_through_its_reaper(
    database: Database, database_dsn: str
) -> None:
    _, _, job_id = seed_job(database_dsn)
    await claim(database)
    expire_lock(database_dsn, job_id)
    worker = Worker(make_env(database, worker_settings(database_dsn), None))

    assert await worker.reap_once() == 1
    assert job_state(database_dsn, job_id)["status"] == "queued"


# --- The lease keeper ------------------------------------------------------------------------


async def test_the_lease_keeper_extends_the_lock_while_the_job_runs(
    database: Database, database_dsn: str
) -> None:
    _, _, job_id = seed_job(database_dsn)
    job = await claim(database, lease_seconds=30)
    assert job is not None
    env = make_env(
        database, worker_settings(database_dsn, job_lease_seconds=5), None, worker_id="worker-a"
    )
    before = job_state(database_dsn, job_id)["locked_until"]

    async with Lease(env, job) as lease:
        await asyncio.sleep(2.2)  # one beat at 5 / 3 s
        lease.check()  # still ours

    after = job_state(database_dsn, job_id)["locked_until"]
    # The beat replaces the claim's 30 s lease with "now + the configured 5 s".
    assert after < before
    assert after - before > -timedelta(seconds=30)


async def test_the_lease_keeper_notices_a_cancel_request(
    database: Database, database_dsn: str
) -> None:
    _, _, job_id = seed_job(database_dsn)
    job = await claim(database)
    assert job is not None
    env = make_env(
        database, worker_settings(database_dsn, job_lease_seconds=5), None, worker_id="worker-a"
    )
    admin(database_dsn).execute(
        "update public.generation_jobs set cancel_requested = true where id = %s", (job_id,)
    )

    async with Lease(env, job) as lease:
        await asyncio.sleep(2.2)
        with pytest.raises(JobCancelled):
            lease.check()


async def test_the_lease_keeper_notices_when_another_worker_took_over(
    database: Database, database_dsn: str
) -> None:
    _, _, job_id = seed_job(database_dsn)
    job = await claim(database)
    assert job is not None
    env = make_env(
        database, worker_settings(database_dsn, job_lease_seconds=5), None, worker_id="worker-a"
    )
    expire_lock(database_dsn, job_id)
    await reap(database)  # the job is back in the queue

    async with Lease(env, job) as lease:
        await asyncio.sleep(2.2)
        with pytest.raises(LeaseLost):
            lease.check()


# --- Backoff ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("attempt", "expected"), [(1, 10.0), (2, 20.0), (3, 40.0), (4, 80.0), (10, 300.0)]
)
def test_backoff_doubles_with_each_attempt_up_to_a_ceiling(attempt: int, expected: float) -> None:
    assert backoff_seconds(attempt, 10.0, jitter=0.5) == expected


def test_backoff_jitter_spreads_retries_between_half_and_one_and_a_half_times() -> None:
    assert backoff_seconds(1, 10.0, jitter=0.0) == 5.0
    assert backoff_seconds(1, 10.0, jitter=0.999) == pytest.approx(14.99, abs=0.01)


def test_a_providers_retry_hint_is_honoured_but_capped() -> None:
    assert backoff_seconds(1, 1.0, jitter=0.5, retry_after=45.0) == 45.0
    assert backoff_seconds(1, 1.0, jitter=0.5, retry_after=99999.0) == 300.0
    assert backoff_seconds(1, 100.0, jitter=0.5, retry_after=5.0) == 100.0


def test_zero_base_means_retry_immediately() -> None:
    assert backoff_seconds(3, 0.0, jitter=0.5) == 0.0


# --- Misc ------------------------------------------------------------------------------------


async def test_a_job_for_a_deleted_goal_disappears_with_it(
    database: Database, database_dsn: str
) -> None:
    user = create_auth_user(database_dsn)
    goal = add_goal(database_dsn, user, status="archived")
    add_job(database_dsn, user, goal)

    admin(database_dsn).execute("delete from public.learning_goals where id = %s", (goal,))

    assert await claim(database) is None
