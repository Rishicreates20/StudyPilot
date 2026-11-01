"""Waking the worker on Vercel (ADR-052): the signal, the middleware, the sender, bounded runs and
the Vercel Queues consumer."""

import asyncio
import re
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from vercel.queue import RetryAfter
from vercel.queue._internal.subscribers import get_subscriptions

from app.ai.factory import builtin_responder
from app.ai.fake import FakeProvider
from app.api.job_wake import JobWakeMiddleware
from app.core.config import JobWakeName, Settings
from app.core.db import Database
from app.core.job_signals import note_job_queued, watch_job_signals
from app.jobs import queue_consumer
from app.jobs.drain import drain, follow_up
from app.jobs.wake import TOPIC, NullWake, VercelQueueWake, build_job_wake
from app.main import create_app
from conftest import Learner, new_client
from support.api_helpers import create_goal, goal_in_status
from support.database import admin, create_auth_user
from support.keys import SigningKey, static_jwks_fetcher
from support.rows import add_goal, add_job
from support.settings import valid_local_settings
from support.worker import clear_queue, job_state, make_env, seed_job, worker_settings

APP_DIR = Path(__file__).resolve().parents[2] / "app"
MakeLearner = Callable[..., Learner]


class RecordingWake:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def wake(self, *, delay_seconds: float = 0.0, key: str | None = None) -> None:
        self.calls.append({"delay_seconds": delay_seconds, "key": key})


# --- The signal --------------------------------------------------------------------------------


def test_the_signal_is_a_no_op_outside_a_watched_request() -> None:
    note_job_queued()  # no error, nothing recorded anywhere

    with watch_job_signals() as queued:
        note_job_queued()
        note_job_queued()
    assert queued == [True, True]


def test_every_place_that_inserts_a_job_signals_it() -> None:
    """A job inserted without the signal would wait until some other job woke the worker."""
    for path in APP_DIR.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        inserts = len(re.findall(r"insert into public\.generation_jobs", source))
        if inserts:
            assert source.count("note_job_queued()") >= inserts, path


# --- The middleware ----------------------------------------------------------------------------


@pytest.fixture
def watched() -> Iterator[tuple[TestClient, RecordingWake]]:
    wake = RecordingWake()
    app = FastAPI()
    app.add_middleware(JobWakeMiddleware, wake=wake)

    @app.post("/queue-two", status_code=202)
    async def queue_two() -> dict[str, str]:
        note_job_queued()
        note_job_queued()
        return {"status": "queued"}

    @app.post("/queue-then-refuse")
    async def queue_then_refuse() -> None:
        from fastapi import HTTPException

        note_job_queued()
        raise HTTPException(status_code=409, detail="refused")

    @app.get("/read")
    async def read() -> dict[str, str]:
        return {"status": "ok"}

    with TestClient(app) as client:
        yield client, wake


def test_a_request_that_queued_jobs_wakes_the_worker_once(
    watched: tuple[TestClient, RecordingWake],
) -> None:
    client, wake = watched

    assert client.post("/queue-two").status_code == 202

    assert wake.calls == [{"delay_seconds": 0.0, "key": None}]


def test_a_refused_request_and_a_read_wake_nothing(
    watched: tuple[TestClient, RecordingWake],
) -> None:
    client, wake = watched

    assert client.post("/queue-then-refuse").status_code == 409
    assert client.get("/read").status_code == 200

    assert wake.calls == []


@pytest.fixture
def waking_api(
    api_settings: Settings, signing_key: SigningKey
) -> Iterator[tuple[TestClient, RecordingWake]]:
    wake = RecordingWake()
    app = create_app(api_settings, jwks_fetcher=static_jwks_fetcher(signing_key), job_wake=wake)
    with new_client(app) as client:
        yield client, wake


def test_starting_a_roadmap_wakes_the_worker_after_the_job_is_stored(
    waking_api: tuple[TestClient, RecordingWake], database_dsn: str, make_learner: MakeLearner
) -> None:
    client, wake = waking_api
    learner = make_learner()
    goal = create_goal(client, learner)

    response = client.post(f"/v1/goals/{goal['id']}/roadmaps", headers=learner.headers, json={})

    assert response.status_code == 202
    assert len(wake.calls) == 1
    stored = admin(database_dsn).fetchone(
        "select status from public.generation_jobs where id = %s", (response.json()["id"],)
    )
    assert stored == {"status": "queued"}


def test_a_refused_roadmap_request_wakes_nothing(
    waking_api: tuple[TestClient, RecordingWake], make_learner: MakeLearner
) -> None:
    client, wake = waking_api
    learner = make_learner()
    goal = goal_in_status(client, learner, "archived")

    response = client.post(f"/v1/goals/{goal['id']}/roadmaps", headers=learner.headers, json={})

    assert response.status_code == 409
    assert wake.calls == []


# --- The sender --------------------------------------------------------------------------------


def run(coroutine: Any) -> Any:
    return asyncio.run(coroutine, loop_factory=asyncio.SelectorEventLoop)


def test_the_vercel_sender_publishes_an_empty_wake_up_on_the_jobs_topic() -> None:
    sent: list[tuple[Any, ...]] = []

    async def send(topic: str, payload: object, **options: object) -> str:
        sent.append((topic, payload, options))
        return "message-1"

    wake = VercelQueueWake(send)
    run(wake.wake())
    run(wake.wake(delay_seconds=90.4, key="run-at-1"))

    assert sent == [
        (TOPIC, {"wake": True}, {"delay": None, "idempotency_key": None}),
        (TOPIC, {"wake": True}, {"delay": 90.4, "idempotency_key": "run-at-1"}),
    ]


def test_a_failed_wake_up_is_tried_once_more_and_never_fails_the_caller() -> None:
    attempts: list[int] = []

    async def send(topic: str, payload: object, **options: object) -> None:
        attempts.append(1)
        raise ConnectionError("queue unreachable")

    run(VercelQueueWake(send, retry_pause=0).wake())

    assert len(attempts) == 2


def test_a_delay_is_capped_at_what_vercel_queues_accepts() -> None:
    delays: list[object] = []

    async def send(topic: str, payload: object, **options: object) -> None:
        delays.append(options["delay"])

    run(VercelQueueWake(send).wake(delay_seconds=30 * 24 * 3600))
    run(VercelQueueWake(send).wake(delay_seconds=-5))

    assert delays == [7 * 24 * 3600.0, None]


def test_the_wake_mode_comes_from_the_settings() -> None:
    assert isinstance(build_job_wake(valid_local_settings()), NullWake)
    vercel = valid_local_settings(job_wake=JobWakeName.VERCEL_QUEUE)
    assert isinstance(build_job_wake(vercel), VercelQueueWake)


# --- Bounded runs -------------------------------------------------------------------------------

pytest_anyio = pytest.mark.anyio


@pytest_anyio
async def test_a_bounded_run_works_through_every_runnable_job(
    database: Database, database_dsn: str
) -> None:
    _, _, first = seed_job(database_dsn)
    _, _, second = seed_job(database_dsn)
    env = make_env(database, worker_settings(database_dsn), FakeProvider(builtin_responder))

    result = await drain(env, budget_seconds=600)

    assert (result.processed, result.out_of_time) == (2, False)
    assert job_state(database_dsn, first)["status"] == "completed"
    assert job_state(database_dsn, second)["status"] == "completed"


@pytest_anyio
async def test_a_bounded_run_starts_no_job_once_its_budget_is_spent(
    database: Database, database_dsn: str
) -> None:
    _, _, job_id = seed_job(database_dsn)
    env = make_env(database, worker_settings(database_dsn), FakeProvider(builtin_responder))
    ticks = iter([0.0, 121.0])

    result = await drain(env, budget_seconds=120, clock=lambda: next(ticks))

    assert (result.processed, result.out_of_time) == (0, True)
    assert job_state(database_dsn, job_id)["status"] == "queued"


@pytest_anyio
async def test_a_bounded_run_first_recovers_a_job_whose_run_was_cut_off(
    database: Database, database_dsn: str
) -> None:
    """The platform stopped an earlier run mid-job: its lease ran out, so this run requeues the
    job (as the long-running worker's reaper would) and then finishes it."""
    user = create_auth_user(database_dsn)
    goal = add_goal(database_dsn, user)
    job_id = add_job(
        database_dsn,
        user,
        goal,
        status="running",
        attempts=1,
        locked_until=datetime.now(UTC) - timedelta(seconds=5),
    )
    env = make_env(database, worker_settings(database_dsn), FakeProvider(builtin_responder))

    result = await drain(env, budget_seconds=600)

    assert (result.recovered, result.processed) == (1, 1)
    assert job_state(database_dsn, job_id)["status"] == "completed"


@pytest_anyio
async def test_follow_up_asks_for_nothing_when_the_queue_is_empty(
    database: Database, database_dsn: str
) -> None:
    clear_queue(database_dsn)
    wake = RecordingWake()
    env = make_env(database, worker_settings(database_dsn), None)

    assert await follow_up(env, wake) is None
    assert wake.calls == []


@pytest_anyio
async def test_follow_up_asks_for_a_run_at_once_when_runnable_work_is_left(
    database: Database, database_dsn: str
) -> None:
    seed_job(database_dsn)
    wake = RecordingWake()
    env = make_env(database, worker_settings(database_dsn), None)

    assert await follow_up(env, wake) == 0.0
    assert wake.calls == [{"delay_seconds": 0.0, "key": None}]


@pytest_anyio
async def test_follow_up_asks_once_for_a_run_when_a_retry_falls_due(
    database: Database, database_dsn: str
) -> None:
    user = create_auth_user(database_dsn)
    goal = add_goal(database_dsn, user)
    run_at = (datetime.now(UTC) + timedelta(seconds=90)).replace(microsecond=0)
    add_job(database_dsn, user, goal, run_at=run_at)
    wake = RecordingWake()
    env = make_env(database, worker_settings(database_dsn), None)
    now = run_at - timedelta(seconds=90)

    delay = await follow_up(env, wake, now=lambda: now)

    assert delay == 90.0
    assert wake.calls == [{"delay_seconds": 90.0, "key": f"run-at-{run_at.timestamp():.0f}"}]


# --- The Vercel Queues consumer ------------------------------------------------------------------


def test_the_consumer_is_one_group_on_the_jobs_topic_with_at_most_two_runs_at_once() -> None:
    mine = [s for s in get_subscriptions() if s.func is queue_consumer.run_jobs]

    assert len(mine) == 1
    subscription = mine[0]
    assert (subscription.topic, subscription.consumer_group) == (TOPIC, "job-runner")
    assert (subscription.max_concurrency, subscription.retry_after_seconds) == (2, 60)


def test_the_consumer_is_declared_for_vercel_in_pyproject() -> None:
    pyproject = (APP_DIR.parent / "pyproject.toml").read_text(encoding="utf-8")

    assert '[[tool.vercel.subscribers]]\nentrypoint = "app.jobs.queue_consumer"' in pyproject


def test_a_run_that_cannot_start_asks_for_redelivery_instead_of_crashing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invalid settings (or an unreachable database) must bring the message back later."""
    from vercel.queue import Message

    def invalid_settings() -> Settings:
        raise ValueError("DATABASE_URL must be set")

    monkeypatch.setattr(queue_consumer, "Settings", invalid_settings)
    message = Message[dict[str, object]](payload={"wake": True}, metadata=_metadata())

    with pytest.raises(RetryAfter):
        run(queue_consumer.run_jobs(message))


def test_a_run_uses_the_bounded_worker_and_acknowledges_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from vercel.queue import Message

    calls: list[Settings] = []

    async def fake_run_bounded(settings: Settings, wake: object) -> None:
        calls.append(settings)
        assert isinstance(wake, VercelQueueWake)

    monkeypatch.setattr(queue_consumer, "Settings", valid_local_settings)
    monkeypatch.setattr(queue_consumer, "run_bounded", fake_run_bounded)

    run(
        queue_consumer.run_jobs(
            Message[dict[str, object]](payload={"wake": True}, metadata=_metadata())
        )
    )

    assert len(calls) == 1


def _metadata() -> Any:
    from vercel.queue import MessageMetadata

    return MessageMetadata(
        message_id="message-1",  # pyright: ignore[reportArgumentType]
        delivery_count=1,
        created_at=datetime.now(UTC),
        topic=TOPIC,
        consumer_group="job-runner",  # pyright: ignore[reportArgumentType]
    )
