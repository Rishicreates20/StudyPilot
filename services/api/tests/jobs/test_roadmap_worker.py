"""The worker generating roadmaps for real: queue -> planner -> validation -> PostgreSQL."""

from collections import defaultdict
from datetime import date
from typing import Any

import pytest
from psycopg.types.json import Jsonb

from app.ai.fake import FakeProvider
from app.ai.fake_roadmap import roadmap_responder, sample_plan
from app.ai.provider import LLMAuthError, LLMRateLimited, LLMUnavailable, StructuredRequest
from app.core.db import Database
from app.jobs import store
from app.jobs.worker import Worker
from support.database import admin, create_auth_user
from support.plans import changed, make_context
from support.rows import add_goal, add_job, add_roadmap
from support.worker import items_of, job_state, make_env, roadmaps_of, seed_job, worker_settings

pytestmark = pytest.mark.anyio


def worker_for(database: Database, dsn: str, provider: Any, **settings: Any) -> Worker:
    return Worker(make_env(database, worker_settings(dsn, **settings), provider))


def sequence(*replies: Any) -> Any:
    """A responder that gives each reply in turn: an exception to raise, or a request -> reply."""
    remaining = list(replies)

    def responder(request: StructuredRequest) -> Any:
        reply = remaining.pop(0)
        return reply if isinstance(reply, BaseException) else reply(request)

    return responder


def over_budget(request: StructuredRequest) -> Any:
    """A reply that breaks the daily limit, to force a repair."""
    return changed(
        sample_plan(request.input_data),
        lambda d: d["modules"][0]["topics"][0].update(estimated_minutes=400),
    )


# --- The happy path --------------------------------------------------------------------------


async def test_a_queued_job_becomes_a_stored_versioned_roadmap(
    database: Database, database_dsn: str
) -> None:
    user, goal, job = seed_job(database_dsn, daily_minutes=60)
    worker = worker_for(database, database_dsn, FakeProvider(roadmap_responder))

    assert await worker.run_once() is True

    state = job_state(database_dsn, job)
    assert (state["status"], state["stage"], state["progress"]) == ("completed", "done", 100)
    assert state["attempts"] == 1
    assert state["finished_at"] is not None
    assert state["locked_by"] is None and state["error_code"] is None
    (roadmap,) = roadmaps_of(database_dsn, goal)
    assert roadmap["user_id"] == user
    assert (roadmap["version"], roadmap["status"]) == (1, "current")
    assert roadmap["job_id"] == job
    assert roadmap["is_synthetic"] is True
    assert roadmap["provider"] == "fake"
    assert roadmap["prompt_version"] == "roadmap-planner/v1"
    assert roadmap["daily_minutes"] == 60
    assert roadmap["syllabus_basis"] in {"learner_stated", "general_knowledge"}


async def test_nothing_to_do_is_reported_as_nothing_done(
    database: Database, database_dsn: str
) -> None:
    worker = worker_for(database, database_dsn, FakeProvider(roadmap_responder))

    # Other tests' jobs are all finished, so the queue is empty here.
    assert await worker.run_once() is False


async def test_the_stored_plan_contains_everything_the_planner_produced(
    database: Database, database_dsn: str
) -> None:
    _, goal, _ = seed_job(database_dsn, daily_minutes=45, preferred_languages=["en"])
    worker = worker_for(database, database_dsn, FakeProvider(roadmap_responder))

    await worker.run_once()

    (roadmap,) = roadmaps_of(database_dsn, goal)
    items = items_of(database_dsn, roadmap["id"])
    kinds: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        kinds[item["kind"]].append(item)
    modules = admin(database_dsn).fetchall(
        "select * from public.roadmap_modules where roadmap_id = %s order by position",
        (roadmap["id"],),
    )
    assert [m["position"] for m in modules] == list(range(1, len(modules) + 1))
    assert len(kinds["topic"]) == roadmap["topic_count"] >= 1
    assert all(
        t["practice_task"] and t["day_number"] and t["objective_ids"] for t in kinds["topic"]
    )
    assert kinds["revision"], "the default learning preferences include revision"
    assert all(e["day_number"] is None for e in kinds["enrichment"])
    assert [item["position"] for item in items] == list(range(1, len(items) + 1))
    assert roadmap["objectives"][0]["id"] == "o1"
    assert roadmap["unknowns"] == []  # not an exam goal
    assert roadmap["assumptions"], "the sample plan states it is a sample"


async def test_totals_are_computed_from_the_stored_items(
    database: Database, database_dsn: str
) -> None:
    _, goal, _ = seed_job(database_dsn)
    await worker_for(database, database_dsn, FakeProvider(roadmap_responder)).run_once()

    (roadmap,) = roadmaps_of(database_dsn, goal)
    items = [i for i in items_of(database_dsn, roadmap["id"]) if i["kind"] != "enrichment"]
    assert roadmap["total_minutes"] == sum(i["estimated_minutes"] for i in items)
    assert roadmap["total_days"] == max(i["day_number"] for i in items)


async def test_prerequisites_are_stored_as_links_between_items(
    database: Database, database_dsn: str
) -> None:
    _, goal, _ = seed_job(database_dsn)
    await worker_for(database, database_dsn, FakeProvider(roadmap_responder)).run_once()

    (roadmap,) = roadmaps_of(database_dsn, goal)
    keys = {i["id"]: i["item_key"] for i in items_of(database_dsn, roadmap["id"])}
    links = admin(database_dsn).fetchall(
        "select item_id, prerequisite_id from public.roadmap_item_prerequisites"
        " where roadmap_id = %s",
        (roadmap["id"],),
    )
    pairs = {(keys[row["item_id"]], keys[row["prerequisite_id"]]) for row in links}
    assert ("part-2", "part-1") in pairs  # a topic depends on the one before it
    assert any(item == "review-everything" for item, _ in pairs)  # a revision revisits topics


async def test_every_model_call_is_recorded_in_the_usage_ledger(
    database: Database, database_dsn: str
) -> None:
    user, _, job = seed_job(database_dsn)
    await worker_for(database, database_dsn, FakeProvider(roadmap_responder)).run_once()

    events = admin(database_dsn).fetchall(
        "select * from public.ai_usage_events where job_id = %s", (job,)
    )
    assert [(e["purpose"], e["provider"], e["error_code"]) for e in events] == [
        ("roadmap.plan", "fake", None)
    ]
    assert events[0]["user_id"] == user
    assert events[0]["prompt_version"] == "roadmap-planner/v1"


# --- The time budget -------------------------------------------------------------------------


@pytest.mark.parametrize("daily_minutes", [10, 30, 60, 240])
async def test_no_stored_day_exceeds_the_learners_daily_minutes(
    database: Database, database_dsn: str, daily_minutes: int
) -> None:
    _, goal, _ = seed_job(database_dsn, daily_minutes=daily_minutes)
    await worker_for(database, database_dsn, FakeProvider(roadmap_responder)).run_once()

    (roadmap,) = roadmaps_of(database_dsn, goal)
    per_day: dict[int, int] = defaultdict(int)
    for item in items_of(database_dsn, roadmap["id"]):
        if item["day_number"] is not None:
            per_day[item["day_number"]] += item["estimated_minutes"]
    assert per_day
    assert max(per_day.values()) <= daily_minutes


async def test_the_plan_ends_before_the_target_date(database: Database, database_dsn: str) -> None:
    # Five days from "today" (2026-10-12), inclusive.
    _, goal, _ = seed_job(database_dsn, daily_minutes=60, target_date=date(2026, 10, 16))
    await worker_for(database, database_dsn, FakeProvider(roadmap_responder)).run_once()

    (roadmap,) = roadmaps_of(database_dsn, goal)
    assert roadmap["total_days"] <= 5
    assert roadmap["target_date"] == date(2026, 10, 16)


async def test_a_goal_with_too_little_time_is_refused_without_calling_the_model(
    database: Database, database_dsn: str
) -> None:
    # Tomorrow at 10 minutes a day: 20 minutes in total.
    _, goal, job = seed_job(database_dsn, daily_minutes=10, target_date=date(2026, 10, 13))
    provider = FakeProvider(script=[])
    await worker_for(database, database_dsn, provider).run_once()

    state = job_state(database_dsn, job)
    assert (state["status"], state["error_code"]) == ("failed", "GOAL_NOT_PLANNABLE")
    assert "too little" in state["error_message"]
    assert provider.requests == []
    assert roadmaps_of(database_dsn, goal) == []


# --- Honesty ---------------------------------------------------------------------------------


async def test_an_exam_goal_is_stored_with_what_could_not_be_verified(
    database: Database, database_dsn: str
) -> None:
    _, goal, _ = seed_job(database_dsn, goal_type="exam", title="Prepare for the board exam")
    await worker_for(database, database_dsn, FakeProvider(roadmap_responder)).run_once()

    (roadmap,) = roadmaps_of(database_dsn, goal)
    assert roadmap["unknowns"], "no official syllabus was supplied, so that must be said"
    assert roadmap["syllabus_basis"] != "uploaded_document"
    assert roadmap["evidence"] == []


# --- Repair and failure ----------------------------------------------------------------------


async def test_a_plan_that_breaks_the_rules_is_repaired_before_it_is_stored(
    database: Database, database_dsn: str
) -> None:
    _, goal, job = seed_job(database_dsn, daily_minutes=60)
    provider = FakeProvider(sequence(over_budget, roadmap_responder))

    await worker_for(database, database_dsn, provider).run_once()

    assert job_state(database_dsn, job)["status"] == "completed"
    assert len(roadmaps_of(database_dsn, goal)) == 1
    purposes = [
        e["purpose"]
        for e in admin(database_dsn).fetchall(
            "select purpose from public.ai_usage_events where job_id = %s order by created_at",
            (job,),
        )
    ]
    assert purposes == ["roadmap.plan", "roadmap.repair"]


async def test_a_plan_that_cannot_be_repaired_fails_the_job_and_stores_nothing(
    database: Database, database_dsn: str
) -> None:
    _, goal, job = seed_job(database_dsn, daily_minutes=60)
    provider = FakeProvider(over_budget)

    await worker_for(database, database_dsn, provider).run_once()

    state = job_state(database_dsn, job)
    assert (state["status"], state["error_code"]) == ("failed", "PLAN_INVALID")
    assert state["attempts"] == 1  # not retried: asking again would not change the constraints
    assert "fits your schedule" in state["error_message"]
    assert len(provider.requests) == 2  # the plan and exactly one repair
    assert roadmaps_of(database_dsn, goal) == []


async def test_a_rejected_api_key_fails_at_once_without_retrying(
    database: Database, database_dsn: str
) -> None:
    _, goal, job = seed_job(database_dsn)
    provider = FakeProvider(script=[LLMAuthError("HTTP 403")])

    await worker_for(database, database_dsn, provider).run_once()

    state = job_state(database_dsn, job)
    assert (state["status"], state["error_code"], state["attempts"]) == (
        "failed",
        "AI_AUTH_FAILED",
        1,
    )
    assert "HTTP 403" not in (state["error_message"] or "")  # provider detail stays in the logs
    assert roadmaps_of(database_dsn, goal) == []


async def test_with_no_provider_configured_the_job_fails_clearly(
    database: Database, database_dsn: str
) -> None:
    _, _, job = seed_job(database_dsn)

    await worker_for(database, database_dsn, None).run_once()

    state = job_state(database_dsn, job)
    assert (state["status"], state["error_code"]) == ("failed", "AI_NOT_CONFIGURED")


# --- Retries ---------------------------------------------------------------------------------


async def test_a_busy_provider_puts_the_job_back_with_a_delay(
    database: Database, database_dsn: str
) -> None:
    _, goal, job = seed_job(database_dsn)
    provider = FakeProvider(script=[LLMRateLimited("quota", retry_after=2.0)])

    await worker_for(database, database_dsn, provider, job_retry_base_seconds=30.0).run_once()

    state = job_state(database_dsn, job)
    assert (state["status"], state["stage"], state["attempts"]) == ("queued", "waiting_retry", 1)
    assert state["error_code"] == "AI_RATE_LIMITED"
    assert "Trying again shortly" in state["error_message"]
    assert state["locked_by"] is None
    delay = admin(database_dsn).scalar(
        "select extract(epoch from run_at - now()) from public.generation_jobs where id = %s",
        (job,),
    )
    assert 20 < float(delay) <= 31  # base 30 s with the test's neutral jitter
    assert roadmaps_of(database_dsn, goal) == []


async def test_a_retry_that_succeeds_completes_the_job_on_the_second_attempt(
    database: Database, database_dsn: str
) -> None:
    _, goal, job = seed_job(database_dsn)
    provider = FakeProvider(sequence(LLMUnavailable("HTTP 503"), roadmap_responder))
    worker = worker_for(database, database_dsn, provider, job_retry_base_seconds=0.0)

    assert await worker.run_once() is True  # attempt 1: fails, goes back to the queue
    assert job_state(database_dsn, job)["status"] == "queued"
    assert await worker.run_once() is True  # attempt 2: succeeds

    state = job_state(database_dsn, job)
    assert (state["status"], state["attempts"], state["error_code"]) == ("completed", 2, None)
    assert len(roadmaps_of(database_dsn, goal)) == 1  # one roadmap, however many attempts


async def test_a_job_that_keeps_failing_gives_up_after_its_attempts(
    database: Database, database_dsn: str
) -> None:
    _, goal, job = seed_job(database_dsn)
    provider = FakeProvider(lambda _request: LLMRateLimited("quota"))
    worker = worker_for(database, database_dsn, provider, job_max_attempts=2)

    await worker.run_once()
    await worker.run_once()

    state = job_state(database_dsn, job)
    assert (state["status"], state["attempts"], state["error_code"]) == (
        "failed",
        2,
        "AI_RATE_LIMITED",
    )
    assert "try again in a few minutes" in state["error_message"]
    assert await worker.run_once() is False  # nothing left to retry
    assert roadmaps_of(database_dsn, goal) == []


async def test_a_retry_does_not_pay_for_planning_again_when_the_plan_was_already_checked(
    database: Database, database_dsn: str
) -> None:
    _, goal, job = seed_job(database_dsn)
    plan = sample_plan(make_context().input_data())
    meta = store.PlanMeta("roadmap-planner/v1", "fake", "fake-planner-1", True, 100, 3, 3)
    admin(database_dsn).execute(
        "update public.generation_jobs set checkpoint = %s where id = %s",
        (Jsonb(store.checkpoint_of(plan, meta)), job),
    )
    provider = FakeProvider(script=[])  # any model call would raise

    await worker_for(database, database_dsn, provider).run_once()

    assert provider.requests == []
    assert job_state(database_dsn, job)["status"] == "completed"
    (roadmap,) = roadmaps_of(database_dsn, goal)
    assert roadmap["title"] == plan.title


# --- Versions --------------------------------------------------------------------------------


async def test_regenerating_adds_a_version_and_keeps_the_old_one_intact(
    database: Database, database_dsn: str
) -> None:
    user, goal, first_job = seed_job(database_dsn)
    worker = worker_for(database, database_dsn, FakeProvider(roadmap_responder))
    await worker.run_once()
    (v1,) = roadmaps_of(database_dsn, goal)
    v1_items = items_of(database_dsn, v1["id"])

    second_job = add_job(database_dsn, user, goal, request=Jsonb({}))
    await worker.run_once()

    first, second = roadmaps_of(database_dsn, goal)
    assert (first["version"], first["status"]) == (1, "superseded")
    assert (second["version"], second["status"]) == (2, "current")
    assert second["job_id"] == second_job and first["job_id"] == first_job
    # The earlier plan is exactly as it was.
    assert {k: first[k] for k in ("title", "overview", "total_minutes")} == {
        k: v1[k] for k in ("title", "overview", "total_minutes")
    }
    assert items_of(database_dsn, first["id"]) == v1_items


async def test_a_revision_request_reaches_the_planner_with_the_previous_plan(
    database: Database, database_dsn: str
) -> None:
    user, goal, _ = seed_job(database_dsn)
    plain = FakeProvider(roadmap_responder)
    await worker_for(database, database_dsn, plain).run_once()
    (v1,) = roadmaps_of(database_dsn, goal)
    add_job(
        database_dsn,
        user,
        goal,
        request=Jsonb({"feedback": "Make it gentler", "base_roadmap_id": str(v1["id"])}),
    )
    provider = FakeProvider(roadmap_responder)

    await worker_for(database, database_dsn, provider).run_once()

    (request,) = provider.requests
    assert request.input_data["revision_feedback"] == "Make it gentler"
    previous = request.input_data["previous_plan"]
    assert previous and previous[0]["topics"][0]["title"].startswith("Part 1")
    _, v2 = roadmaps_of(database_dsn, goal)
    assert v2["revision_feedback"] == "Make it gentler"
    assert v2["based_on_roadmap_id"] == v1["id"]
    assert any("revision was requested" in a for a in v2["assumptions"])


async def test_a_fresh_regeneration_does_not_show_the_planner_the_old_plan(
    database: Database, database_dsn: str
) -> None:
    user, goal, _ = seed_job(database_dsn)
    await worker_for(database, database_dsn, FakeProvider(roadmap_responder)).run_once()
    add_job(database_dsn, user, goal, request=Jsonb({}))
    provider = FakeProvider(roadmap_responder)

    await worker_for(database, database_dsn, provider).run_once()

    (request,) = provider.requests
    assert request.input_data["previous_plan"] is None
    assert request.input_data["revision_feedback"] is None


# --- Exactly once ----------------------------------------------------------------------------


async def test_a_job_that_already_has_a_roadmap_does_not_get_a_second_one(
    database: Database, database_dsn: str
) -> None:
    user, goal, job = seed_job(database_dsn)
    existing = add_roadmap(database_dsn, user, goal, job)  # e.g. stored just before a crash

    await worker_for(database, database_dsn, FakeProvider(roadmap_responder)).run_once()

    assert [r["id"] for r in roadmaps_of(database_dsn, goal)] == [existing]
    assert job_state(database_dsn, job)["status"] == "completed"


# --- The goal changes under the job's feet ---------------------------------------------------


async def test_a_goal_archived_while_the_job_waited_fails_the_job(
    database: Database, database_dsn: str
) -> None:
    _, goal, job = seed_job(database_dsn)
    admin(database_dsn).execute(
        "update public.learning_goals set status = 'archived' where id = %s", (goal,)
    )
    provider = FakeProvider(script=[])

    await worker_for(database, database_dsn, provider).run_once()

    state = job_state(database_dsn, job)
    assert (state["status"], state["error_code"]) == ("failed", "GOAL_UNAVAILABLE")
    assert provider.requests == []
    assert roadmaps_of(database_dsn, goal) == []


async def test_a_goal_archived_while_the_model_was_thinking_stores_nothing(
    database: Database, database_dsn: str
) -> None:
    _, goal, job = seed_job(database_dsn)

    def archive_then_answer(request: StructuredRequest) -> Any:
        admin(database_dsn).execute(
            "update public.learning_goals set status = 'archived' where id = %s", (goal,)
        )
        return roadmap_responder(request)

    await worker_for(database, database_dsn, FakeProvider(archive_then_answer)).run_once()

    state = job_state(database_dsn, job)
    assert (state["status"], state["error_code"]) == ("failed", "GOAL_UNAVAILABLE")
    assert roadmaps_of(database_dsn, goal) == []


async def test_a_cancel_request_stops_the_job_before_anything_is_stored(
    database: Database, database_dsn: str
) -> None:
    _, goal, job = seed_job(database_dsn)

    def cancel_then_answer(request: StructuredRequest) -> Any:
        admin(database_dsn).execute(
            "update public.generation_jobs set cancel_requested = true where id = %s", (job,)
        )
        return roadmap_responder(request)

    await worker_for(database, database_dsn, FakeProvider(cancel_then_answer)).run_once()

    state = job_state(database_dsn, job)
    assert (state["status"], state["stage"]) == ("cancelled", "cancelled")
    assert state["finished_at"] is not None
    assert roadmaps_of(database_dsn, goal) == []


async def test_a_job_cancelled_while_queued_is_never_picked_up(
    database: Database, database_dsn: str
) -> None:
    _, _, job = seed_job(database_dsn)
    admin(database_dsn).execute(
        "update public.generation_jobs set cancel_requested = true where id = %s", (job,)
    )
    provider = FakeProvider(script=[])

    assert await worker_for(database, database_dsn, provider).run_once() is False
    assert job_state(database_dsn, job)["status"] == "cancelled"
    assert provider.requests == []


# --- Ownership -------------------------------------------------------------------------------


async def test_each_learners_plan_is_stored_under_that_learner_only(
    database: Database, database_dsn: str
) -> None:
    alice, alice_goal, alice_job = seed_job(database_dsn, title="Learn Alice's thing")
    bob, bob_goal, bob_job = seed_job(database_dsn, title="Learn Bob's thing")
    worker = worker_for(database, database_dsn, FakeProvider(roadmap_responder))

    await worker.run_once()
    await worker.run_once()

    (alice_roadmap,) = roadmaps_of(database_dsn, alice_goal)
    (bob_roadmap,) = roadmaps_of(database_dsn, bob_goal)
    assert (alice_roadmap["user_id"], bob_roadmap["user_id"]) == (alice, bob)
    assert "Alice" in alice_roadmap["title"] and "Bob" in bob_roadmap["title"]
    assert job_state(database_dsn, alice_job)["status"] == "completed"
    assert job_state(database_dsn, bob_job)["status"] == "completed"
    with admin(database_dsn).acting_as("authenticated", alice) as connection:
        visible = [r["user_id"] for r in connection.execute("select user_id from public.roadmaps")]
    assert set(visible) == {alice}


async def test_a_revision_cannot_be_based_on_someone_elses_roadmap(
    database: Database, database_dsn: str
) -> None:
    _, alice_goal, _ = seed_job(database_dsn)
    await worker_for(database, database_dsn, FakeProvider(roadmap_responder)).run_once()
    (alice_roadmap,) = roadmaps_of(database_dsn, alice_goal)
    bob = create_auth_user(database_dsn)
    bob_goal = add_goal(database_dsn, bob)
    add_job(
        database_dsn,
        bob,
        bob_goal,
        request=Jsonb({"feedback": "Use hers", "base_roadmap_id": str(alice_roadmap["id"])}),
    )
    provider = FakeProvider(roadmap_responder)

    await worker_for(database, database_dsn, provider).run_once()

    (request,) = provider.requests
    assert request.input_data["previous_plan"] is None  # Alice's plan was not loaded for Bob
    (bob_roadmap,) = roadmaps_of(database_dsn, bob_goal)
    assert bob_roadmap["based_on_roadmap_id"] is None
