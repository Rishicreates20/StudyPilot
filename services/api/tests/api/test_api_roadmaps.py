"""Roadmap generation through the HTTP API: ownership, validation, jobs and versions."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response

from conftest import Learner
from support.api_helpers import create_goal, goal_in_status
from support.database import admin
from support.worker import clear_queue, run_worker_once

MakeLearner = Callable[..., Learner]


def start(
    api: TestClient,
    learner: Learner,
    goal_id: str,
    /,
    *,
    headers: dict[str, str] | None = None,
    **body: Any,
) -> Response:
    return api.post(
        f"/v1/goals/{goal_id}/roadmaps",
        headers={**learner.headers, **(headers or {})},
        json=body,
    )


def generate(
    api: TestClient, dsn: str, learner: Learner, goal_id: str, /, **body: Any
) -> dict[str, Any]:
    """Start a generation and run it to completion with the real worker. Returns the job."""
    clear_queue(dsn)  # leftovers from other tests must not be picked up instead of this job
    response = start(api, learner, goal_id, **body)
    assert response.status_code == 202, response.text
    assert run_worker_once(dsn) is True
    job = api.get(f"/v1/jobs/{response.json()['id']}", headers=learner.headers).json()
    assert job["status"] == "completed", job
    return job


def finish_jobs(dsn: str, goal_id: str, status: str = "completed") -> None:
    """Mark a goal's unfinished jobs finished, the way the worker eventually would."""
    admin(dsn).execute(
        "update public.generation_jobs set status = %s, stage = 'done', finished_at = now(),"
        " locked_by = null, locked_until = null,"
        " error_code = case when %s = 'failed' then 'TEST_FAILURE' end"
        " where goal_id = %s and status in ('queued', 'running')",
        (status, status, goal_id),
    )


# --- Authentication and ownership on every endpoint ------------------------------------------

ENDPOINTS: list[tuple[str, str, dict[str, Any] | None]] = [
    ("post", "/v1/goals/{goal}/roadmaps", {}),
    ("get", "/v1/goals/{goal}/roadmaps", None),
    ("get", "/v1/goals/{goal}/jobs", None),
    ("get", "/v1/roadmaps/{roadmap}", None),
    ("post", "/v1/roadmaps/{roadmap}/make-current", None),
    ("get", "/v1/jobs/{job}", None),
    ("post", "/v1/jobs/{job}/cancel", None),
    ("post", "/v1/jobs/{job}/retry", None),
]


@pytest.fixture
def owned(api: TestClient, database_dsn: str, make_learner: MakeLearner) -> dict[str, Any]:
    """Alice with a goal, a finished generation and its roadmap; Bob with nothing."""
    alice, bob = make_learner(), make_learner()
    goal = create_goal(api, alice)
    job = generate(api, database_dsn, alice, goal["id"])
    return {
        "alice": alice,
        "bob": bob,
        "goal": goal["id"],
        "job": job["id"],
        "roadmap": job["roadmap_id"],
    }


def url_for(template: str, owned: dict[str, Any]) -> str:
    return template.format(goal=owned["goal"], roadmap=owned["roadmap"], job=owned["job"])


@pytest.mark.parametrize(("method", "template", "body"), ENDPOINTS)
def test_every_endpoint_requires_a_token(
    api: TestClient, owned: dict[str, Any], method: str, template: str, body: Any
) -> None:
    response = api.request(method, url_for(template, owned), json=body)

    assert response.status_code == 401


@pytest.mark.parametrize(("method", "template", "body"), ENDPOINTS)
def test_every_endpoint_rejects_a_bad_token(
    api: TestClient, owned: dict[str, Any], method: str, template: str, body: Any
) -> None:
    response = api.request(
        method, url_for(template, owned), json=body, headers={"Authorization": "Bearer nonsense"}
    )

    assert response.status_code == 401


@pytest.mark.parametrize(("method", "template", "body"), ENDPOINTS)
def test_another_learners_resources_are_not_found(
    api: TestClient, owned: dict[str, Any], method: str, template: str, body: Any
) -> None:
    response = api.request(
        method, url_for(template, owned), json=body, headers=owned["bob"].headers
    )

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")


@pytest.mark.parametrize(("method", "template", "body"), ENDPOINTS)
def test_missing_resources_look_exactly_like_other_peoples(
    api: TestClient, owned: dict[str, Any], method: str, template: str, body: Any
) -> None:
    missing = {"goal": str(uuid4()), "roadmap": str(uuid4()), "job": str(uuid4())}
    theirs = api.request(method, url_for(template, owned), json=body, headers=owned["bob"].headers)
    nothing = api.request(
        method, template.format(**missing), json=body, headers=owned["alice"].headers
    )

    assert (nothing.status_code, nothing.json()["code"]) == (
        theirs.status_code,
        theirs.json()["code"],
    )


def test_another_learner_cannot_start_a_generation_for_my_goal_and_nothing_is_queued(
    api: TestClient, database_dsn: str, make_learner: MakeLearner
) -> None:
    alice, bob = make_learner(), make_learner()
    goal = create_goal(api, alice)

    response = start(api, bob, goal["id"])

    assert response.status_code == 404
    assert (
        admin(database_dsn).scalar(
            "select count(*) from public.generation_jobs where goal_id = %s", (goal["id"],)
        )
        == 0
    )


def test_a_malformed_id_is_a_validation_error_not_a_crash(
    api: TestClient, make_learner: MakeLearner
) -> None:
    learner = make_learner()

    assert api.get("/v1/jobs/not-a-uuid", headers=learner.headers).status_code == 422
    assert api.get("/v1/roadmaps/12345", headers=learner.headers).status_code == 422


# --- Starting a generation -------------------------------------------------------------------


def test_starting_queues_a_job_and_returns_at_once(
    api: TestClient, database_dsn: str, make_learner: MakeLearner
) -> None:
    learner = make_learner()
    goal = create_goal(api, learner)

    response = start(api, learner, goal["id"])

    assert response.status_code == 202
    job = response.json()
    assert response.headers["location"] == f"/v1/jobs/{job['id']}"
    assert (job["status"], job["stage"], job["progress"], job["attempts"]) == (
        "queued",
        "queued",
        0,
        0,
    )
    assert job["goal_id"] == goal["id"] and job["job_type"] == "roadmap"
    assert job["roadmap_id"] is None and job["error_code"] is None
    row = admin(database_dsn).fetchone(
        "select user_id, request from public.generation_jobs where id = %s", (job["id"],)
    )
    assert row == {"user_id": learner.id, "request": {}}  # owned by the caller; nothing else asked


def test_the_response_exposes_no_internal_fields(
    api: TestClient, make_learner: MakeLearner
) -> None:
    learner = make_learner()
    job = start(api, learner, create_goal(api, learner)["id"]).json()

    assert set(job) == {
        "id", "goal_id", "job_type", "status", "stage", "progress", "attempts", "max_attempts",
        "cancel_requested", "error_code", "error_message", "roadmap_id", "created_at", "item_id",
        "lesson_id", "attempt_id", "quiz_id", "started_at", "finished_at",
    }  # fmt: skip


@pytest.mark.parametrize(
    "body",
    [
        {"user_id": str(uuid4())},
        {"status": "completed"},
        {"goal_id": str(uuid4())},
        {"feedback": "x" * 501},
        {"feedback": 42},
    ],
)
def test_unknown_or_oversized_fields_are_rejected(
    api: TestClient, make_learner: MakeLearner, body: dict[str, Any]
) -> None:
    learner = make_learner()
    goal = create_goal(api, learner)

    response = start(api, learner, goal["id"], **body)

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_blank_feedback_means_a_fresh_plan(
    api: TestClient, database_dsn: str, make_learner: MakeLearner
) -> None:
    learner = make_learner()
    goal = create_goal(api, learner)

    job = start(api, learner, goal["id"], feedback="   ").json()

    assert (
        admin(database_dsn).scalar(
            "select request from public.generation_jobs where id = %s", (job["id"],)
        )
        == {}
    )


def test_a_goal_that_is_too_vague_cannot_be_planned(
    api: TestClient, make_learner: MakeLearner
) -> None:
    learner = make_learner()
    goal = create_goal(api, learner, title="ab")

    response = start(api, learner, goal["id"])

    assert response.status_code == 422
    assert response.json()["code"] == "GOAL_NOT_PLANNABLE"
    assert "title" in response.json()["detail"]


def test_a_target_date_that_leaves_too_little_time_is_refused_with_advice(
    api: TestClient, database_dsn: str, make_learner: MakeLearner
) -> None:
    learner = make_learner()
    tomorrow = (datetime.now(UTC) + timedelta(days=1)).date().isoformat()
    goal = create_goal(api, learner, daily_minutes=10, target_date=tomorrow)

    response = start(api, learner, goal["id"])

    assert response.status_code == 422
    assert response.json()["code"] == "GOAL_NOT_PLANNABLE"
    assert "daily minutes" in response.json()["detail"]
    assert (
        admin(database_dsn).scalar(
            "select count(*) from public.generation_jobs where goal_id = %s", (goal["id"],)
        )
        == 0
    )


def test_an_archived_goal_cannot_get_a_roadmap(api: TestClient, make_learner: MakeLearner) -> None:
    learner = make_learner()
    goal = goal_in_status(api, learner, "archived")

    response = start(api, learner, goal["id"])

    assert response.status_code == 409
    assert response.json()["code"] == "GOAL_ARCHIVED"


@pytest.mark.parametrize("status", ["paused", "completed"])
def test_paused_and_completed_goals_can_still_get_a_roadmap(
    api: TestClient, make_learner: MakeLearner, status: str
) -> None:
    learner = make_learner()
    goal = goal_in_status(api, learner, status)

    assert start(api, learner, goal["id"]).status_code == 202


def test_without_an_ai_provider_nothing_is_queued(
    api: TestClient, database_dsn: str, make_learner: MakeLearner, no_ai: None
) -> None:
    learner = make_learner()
    goal = create_goal(api, learner)

    response = start(api, learner, goal["id"])

    assert response.status_code == 503
    assert response.json()["code"] == "AI_NOT_CONFIGURED"
    assert (
        admin(database_dsn).scalar(
            "select count(*) from public.generation_jobs where goal_id = %s", (goal["id"],)
        )
        == 0
    )


# --- One at a time, idempotency, allowance ---------------------------------------------------


def test_a_second_generation_cannot_start_while_one_is_active(
    api: TestClient, database_dsn: str, make_learner: MakeLearner
) -> None:
    learner = make_learner()
    goal = create_goal(api, learner)
    first = start(api, learner, goal["id"])
    assert first.status_code == 202

    second = start(api, learner, goal["id"])

    assert second.status_code == 409
    assert second.json()["code"] == "ROADMAP_JOB_ACTIVE"
    assert (
        admin(database_dsn).scalar(
            "select count(*) from public.generation_jobs where goal_id = %s", (goal["id"],)
        )
        == 1
    )

    finish_jobs(database_dsn, goal["id"])
    assert start(api, learner, goal["id"]).status_code == 202  # fine once the first is done


def test_goals_generate_independently(api: TestClient, make_learner: MakeLearner) -> None:
    learner = make_learner()

    assert start(api, learner, create_goal(api, learner)["id"]).status_code == 202
    assert start(api, learner, create_goal(api, learner)["id"]).status_code == 202


def test_resubmitting_with_the_same_key_returns_the_same_job(
    api: TestClient, database_dsn: str, make_learner: MakeLearner
) -> None:
    learner = make_learner()
    goal = create_goal(api, learner)
    headers = {"Idempotency-Key": "form-submission-0001"}

    first = start(api, learner, goal["id"], headers=headers)
    again = start(api, learner, goal["id"], headers=headers)

    assert (first.status_code, again.status_code) == (202, 202)
    assert first.json()["id"] == again.json()["id"]
    assert (
        admin(database_dsn).scalar(
            "select count(*) from public.generation_jobs where goal_id = %s", (goal["id"],)
        )
        == 1
    )


def test_a_replay_still_works_after_the_job_has_finished(
    api: TestClient, database_dsn: str, make_learner: MakeLearner
) -> None:
    learner = make_learner()
    goal = create_goal(api, learner)
    headers = {"Idempotency-Key": "form-submission-0002"}
    first = start(api, learner, goal["id"], headers=headers).json()
    finish_jobs(database_dsn, goal["id"])

    again = start(api, learner, goal["id"], headers=headers)

    assert again.status_code == 202 and again.json()["id"] == first["id"]


def test_the_same_key_for_a_different_request_is_a_conflict(
    api: TestClient, make_learner: MakeLearner
) -> None:
    learner = make_learner()
    goal = create_goal(api, learner)
    headers = {"Idempotency-Key": "form-submission-0003"}
    start(api, learner, goal["id"], headers=headers)

    different = start(api, learner, goal["id"], headers=headers, feedback="Make it shorter")
    other_goal = start(api, learner, create_goal(api, learner)["id"], headers=headers)

    assert different.status_code == other_goal.status_code == 409
    assert different.json()["code"] == other_goal.json()["code"] == "IDEMPOTENCY_KEY_REUSED"


def test_two_learners_may_use_the_same_key(api: TestClient, make_learner: MakeLearner) -> None:
    alice, bob = make_learner(), make_learner()
    headers = {"Idempotency-Key": "shared-by-chance-1"}

    first = start(api, alice, create_goal(api, alice)["id"], headers=headers)
    second = start(api, bob, create_goal(api, bob)["id"], headers=headers)

    assert (first.status_code, second.status_code) == (202, 202)
    assert first.json()["id"] != second.json()["id"]


def test_a_key_must_be_long_enough_to_be_unguessable(
    api: TestClient, make_learner: MakeLearner
) -> None:
    learner = make_learner()

    response = start(
        api, learner, create_goal(api, learner)["id"], headers={"Idempotency-Key": "short"}
    )

    assert response.status_code == 422


def test_the_daily_allowance_limits_generations(
    api: TestClient,
    database_dsn: str,
    make_learner: MakeLearner,
    configure_app: Callable[..., None],
) -> None:
    configure_app(roadmap_jobs_per_user_per_day=2)
    learner = make_learner()
    goal = create_goal(api, learner)
    for _ in range(2):
        assert start(api, learner, goal["id"]).status_code == 202
        finish_jobs(database_dsn, goal["id"])

    response = start(api, learner, goal["id"])

    assert response.status_code == 429
    assert response.json()["code"] == "GENERATION_LIMIT_REACHED"


def test_the_allowance_is_per_learner(
    api: TestClient,
    database_dsn: str,
    make_learner: MakeLearner,
    configure_app: Callable[..., None],
) -> None:
    configure_app(roadmap_jobs_per_user_per_day=1)
    alice, bob = make_learner(), make_learner()
    alice_goal = create_goal(api, alice)
    assert start(api, alice, alice_goal["id"]).status_code == 202
    finish_jobs(database_dsn, alice_goal["id"])

    assert start(api, alice, alice_goal["id"]).status_code == 429
    assert start(api, bob, create_goal(api, bob)["id"]).status_code == 202


# --- Following a job -------------------------------------------------------------------------


def test_a_job_can_be_read_and_listed_by_its_owner(
    api: TestClient, make_learner: MakeLearner
) -> None:
    learner = make_learner()
    goal = create_goal(api, learner)
    job = start(api, learner, goal["id"]).json()

    read = api.get(f"/v1/jobs/{job['id']}", headers=learner.headers)
    listed = api.get(f"/v1/goals/{goal['id']}/jobs", headers=learner.headers)

    assert read.status_code == 200 and read.json() == job
    assert [j["id"] for j in listed.json()["items"]] == [job["id"]]


def test_jobs_are_listed_newest_first_and_limited(
    api: TestClient, database_dsn: str, make_learner: MakeLearner
) -> None:
    learner = make_learner()
    goal = create_goal(api, learner)
    ids: list[str] = []
    for _ in range(3):
        ids.append(start(api, learner, goal["id"]).json()["id"])
        finish_jobs(database_dsn, goal["id"])

    everything = api.get(f"/v1/goals/{goal['id']}/jobs", headers=learner.headers).json()["items"]
    limited = api.get(f"/v1/goals/{goal['id']}/jobs?limit=2", headers=learner.headers).json()[
        "items"
    ]

    assert [j["id"] for j in everything] == ids[::-1]
    assert [j["id"] for j in limited] == ids[::-1][:2]
    assert (
        api.get(f"/v1/goals/{goal['id']}/jobs?limit=99", headers=learner.headers).status_code == 422
    )


def test_a_finished_job_points_to_its_roadmap(owned: dict[str, Any], api: TestClient) -> None:
    job = api.get(f"/v1/jobs/{owned['job']}", headers=owned["alice"].headers).json()

    assert job["status"] == "completed"
    assert (job["stage"], job["progress"]) == ("done", 100)
    assert job["roadmap_id"] == owned["roadmap"]
    assert job["finished_at"] is not None


# --- Cancelling and retrying -----------------------------------------------------------------


def test_cancelling_a_queued_job_cancels_it_at_once(
    api: TestClient, make_learner: MakeLearner
) -> None:
    learner = make_learner()
    job = start(api, learner, create_goal(api, learner)["id"]).json()

    response = api.post(f"/v1/jobs/{job['id']}/cancel", headers=learner.headers)

    assert response.status_code == 200
    assert (response.json()["status"], response.json()["stage"]) == ("cancelled", "cancelled")
    assert response.json()["finished_at"] is not None


def test_cancelling_a_running_job_only_asks_it_to_stop(
    api: TestClient, database_dsn: str, make_learner: MakeLearner
) -> None:
    learner = make_learner()
    job = start(api, learner, create_goal(api, learner)["id"]).json()
    admin(database_dsn).execute(
        "update public.generation_jobs set status = 'running', locked_by = 'w',"
        " locked_until = now() + interval '1 minute' where id = %s",
        (job["id"],),
    )

    response = api.post(f"/v1/jobs/{job['id']}/cancel", headers=learner.headers)

    assert response.status_code == 200
    assert (response.json()["status"], response.json()["cancel_requested"]) == ("running", True)


def test_cancelling_a_finished_job_changes_nothing(owned: dict[str, Any], api: TestClient) -> None:
    response = api.post(f"/v1/jobs/{owned['job']}/cancel", headers=owned["alice"].headers)

    assert response.status_code == 200
    assert response.json()["status"] == "completed"


def test_a_cancelled_goal_can_generate_again(api: TestClient, make_learner: MakeLearner) -> None:
    learner = make_learner()
    goal = create_goal(api, learner)
    job = start(api, learner, goal["id"]).json()
    api.post(f"/v1/jobs/{job['id']}/cancel", headers=learner.headers)

    assert start(api, learner, goal["id"]).status_code == 202


def failed_job(
    api: TestClient, dsn: str, learner: Learner, goal_id: str, /, **body: Any
) -> dict[str, Any]:
    job = start(api, learner, goal_id, **body).json()
    finish_jobs(dsn, goal_id, "failed")
    return api.get(f"/v1/jobs/{job['id']}", headers=learner.headers).json()


def test_a_failed_generation_can_be_retried_as_a_new_job(
    api: TestClient, database_dsn: str, make_learner: MakeLearner
) -> None:
    learner = make_learner()
    goal = create_goal(api, learner)
    failed = failed_job(api, database_dsn, learner, goal["id"], feedback="Add more practice")
    assert failed["status"] == "failed"

    response = api.post(f"/v1/jobs/{failed['id']}/retry", headers=learner.headers)

    assert response.status_code == 202
    retry = response.json()
    assert retry["id"] != failed["id"] and retry["status"] == "queued"
    assert response.headers["location"] == f"/v1/jobs/{retry['id']}"
    assert (
        admin(database_dsn).scalar(
            "select request->>'feedback' from public.generation_jobs where id = %s", (retry["id"],)
        )
        == "Add more practice"
    )
    assert api.get(f"/v1/jobs/{failed['id']}", headers=learner.headers).json()["status"] == "failed"


@pytest.mark.parametrize("state", ["queued", "completed", "cancelled"])
def test_only_failed_generations_can_be_retried(
    api: TestClient, database_dsn: str, make_learner: MakeLearner, state: str
) -> None:
    learner = make_learner()
    goal = create_goal(api, learner)
    job = start(api, learner, goal["id"]).json()
    if state != "queued":
        finish_jobs(database_dsn, goal["id"], state)

    response = api.post(f"/v1/jobs/{job['id']}/retry", headers=learner.headers)

    assert response.status_code == 409
    assert response.json()["code"] == "JOB_NOT_RETRYABLE"


def test_a_retry_is_refused_while_another_generation_is_active(
    api: TestClient, database_dsn: str, make_learner: MakeLearner
) -> None:
    learner = make_learner()
    goal = create_goal(api, learner)
    failed = failed_job(api, database_dsn, learner, goal["id"])
    assert start(api, learner, goal["id"]).status_code == 202

    response = api.post(f"/v1/jobs/{failed['id']}/retry", headers=learner.headers)

    assert response.status_code == 409
    assert response.json()["code"] == "ROADMAP_JOB_ACTIVE"


# --- Reading roadmaps ------------------------------------------------------------------------


def test_a_generated_roadmap_can_be_read_with_its_full_structure(
    owned: dict[str, Any], api: TestClient
) -> None:
    response = api.get(f"/v1/roadmaps/{owned['roadmap']}", headers=owned["alice"].headers)

    assert response.status_code == 200
    roadmap = response.json()
    assert (roadmap["version"], roadmap["status"], roadmap["goal_id"]) == (
        1,
        "current",
        owned["goal"],
    )
    assert roadmap["title"] and roadmap["overview"] and roadmap["target_outcome"]
    assert roadmap["is_synthetic"] is True  # the built-in test provider produced it
    assert roadmap["syllabus_basis"] in {"learner_stated", "general_knowledge"}
    assert roadmap["objectives"][0] == {"id": "o1", "text": roadmap["objectives"][0]["text"]}
    topics = [t for m in roadmap["modules"] for t in m["topics"]]
    assert len(topics) == roadmap["topic_count"] >= 1
    assert [m["position"] for m in roadmap["modules"]] == list(
        range(1, len(roadmap["modules"]) + 1)
    )
    assert all(t["kind"] == "topic" and t["practice_task"] and t["day_number"] for t in topics)
    assert roadmap["revision_sessions"] and roadmap["enrichment"]
    assert all(e["day_number"] is None for e in roadmap["enrichment"])


def test_prerequisite_ids_point_at_earlier_items_of_the_same_roadmap(
    owned: dict[str, Any], api: TestClient
) -> None:
    roadmap = api.get(f"/v1/roadmaps/{owned['roadmap']}", headers=owned["alice"].headers).json()

    topics = [t for m in roadmap["modules"] for t in m["topics"]]
    by_id = {t["id"]: t for t in topics}
    assert any(t["prerequisite_ids"] for t in topics)
    for topic in topics:
        for prerequisite in topic["prerequisite_ids"]:
            assert by_id[prerequisite]["position"] < topic["position"]
            assert by_id[prerequisite]["day_number"] <= topic["day_number"]
    revision = roadmap["revision_sessions"][0]
    assert set(revision["prerequisite_ids"]) <= set(by_id)  # a revision revisits topics


def test_totals_in_the_response_match_the_schedule(owned: dict[str, Any], api: TestClient) -> None:
    roadmap = api.get(f"/v1/roadmaps/{owned['roadmap']}", headers=owned["alice"].headers).json()

    scheduled = [
        *(t for m in roadmap["modules"] for t in m["topics"]),
        *roadmap["revision_sessions"],
    ]
    assert roadmap["total_minutes"] == sum(i["estimated_minutes"] for i in scheduled)
    assert roadmap["total_days"] == max(i["day_number"] for i in scheduled)
    per_day: dict[int, int] = {}
    for item in scheduled:
        per_day[item["day_number"]] = per_day.get(item["day_number"], 0) + item["estimated_minutes"]
    assert max(per_day.values()) <= roadmap["daily_minutes"]


def test_roadmap_responses_leak_no_internal_fields(owned: dict[str, Any], api: TestClient) -> None:
    text = api.get(f"/v1/roadmaps/{owned['roadmap']}", headers=owned["alice"].headers).text
    listing = api.get(f"/v1/goals/{owned['goal']}/roadmaps", headers=owned["alice"].headers).text

    for forbidden in ("user_id", "job_id", '"provider"', "model_id", "checkpoint", "request"):
        assert forbidden not in text and forbidden not in listing


def test_versions_are_listed_newest_first_with_the_current_one_marked(
    api: TestClient, database_dsn: str, make_learner: MakeLearner
) -> None:
    learner = make_learner()
    goal = create_goal(api, learner)
    first = generate(api, database_dsn, learner, goal["id"])
    second = generate(api, database_dsn, learner, goal["id"], feedback="Fewer topics")

    listing = api.get(f"/v1/goals/{goal['id']}/roadmaps", headers=learner.headers).json()

    assert [(v["version"], v["status"]) for v in listing["items"]] == [
        (2, "current"),
        (1, "superseded"),
    ]
    assert listing["current_id"] == second["roadmap_id"]
    assert listing["items"][1]["id"] == first["roadmap_id"]
    assert listing["items"][0]["revision_feedback"] == "Fewer topics"
    assert listing["items"][0]["based_on_roadmap_id"] == first["roadmap_id"]


def test_an_earlier_version_stays_readable_and_unchanged(
    api: TestClient, database_dsn: str, make_learner: MakeLearner
) -> None:
    learner = make_learner()
    goal = create_goal(api, learner)
    first = generate(api, database_dsn, learner, goal["id"])
    before = api.get(f"/v1/roadmaps/{first['roadmap_id']}", headers=learner.headers).json()

    generate(api, database_dsn, learner, goal["id"])
    after = api.get(f"/v1/roadmaps/{first['roadmap_id']}", headers=learner.headers).json()

    assert after.pop("status") == "superseded" and before.pop("status") == "current"
    assert after == before


def test_a_goal_without_a_roadmap_lists_none(api: TestClient, make_learner: MakeLearner) -> None:
    learner = make_learner()

    listing = api.get(
        f"/v1/goals/{create_goal(api, learner)['id']}/roadmaps", headers=learner.headers
    )

    assert listing.status_code == 200
    assert listing.json() == {"items": [], "current_id": None}


# --- Switching versions ----------------------------------------------------------------------


def two_versions(api: TestClient, dsn: str, learner: Learner) -> tuple[str, str, str]:
    goal = create_goal(api, learner)
    first = generate(api, dsn, learner, goal["id"])
    second = generate(api, dsn, learner, goal["id"])
    return goal["id"], first["roadmap_id"], second["roadmap_id"]


def test_an_earlier_version_can_be_made_current_without_losing_the_newer_one(
    api: TestClient, database_dsn: str, make_learner: MakeLearner
) -> None:
    learner = make_learner()
    goal, first, second = two_versions(api, database_dsn, learner)

    response = api.post(f"/v1/roadmaps/{first}/make-current", headers=learner.headers)

    assert response.status_code == 200
    assert (response.json()["id"], response.json()["status"]) == (first, "current")
    listing = api.get(f"/v1/goals/{goal}/roadmaps", headers=learner.headers).json()
    assert listing["current_id"] == first
    assert {v["id"]: v["status"] for v in listing["items"]} == {
        first: "current",
        second: "superseded",
    }
    assert api.get(f"/v1/roadmaps/{second}", headers=learner.headers).status_code == 200


def test_making_the_current_version_current_again_changes_nothing(
    api: TestClient, database_dsn: str, make_learner: MakeLearner
) -> None:
    learner = make_learner()
    _, _, second = two_versions(api, database_dsn, learner)

    response = api.post(f"/v1/roadmaps/{second}/make-current", headers=learner.headers)

    assert response.status_code == 200 and response.json()["status"] == "current"


def test_versions_of_an_archived_goal_cannot_be_switched(
    api: TestClient, database_dsn: str, make_learner: MakeLearner
) -> None:
    learner = make_learner()
    goal, first, _ = two_versions(api, database_dsn, learner)
    api.put(f"/v1/goals/{goal}/status", headers=learner.headers, json={"status": "archived"})

    response = api.post(f"/v1/roadmaps/{first}/make-current", headers=learner.headers)

    assert response.status_code == 409
    assert response.json()["code"] == "GOAL_ARCHIVED"


def test_a_new_generation_after_switching_back_continues_the_numbering(
    api: TestClient, database_dsn: str, make_learner: MakeLearner
) -> None:
    learner = make_learner()
    goal, first, _ = two_versions(api, database_dsn, learner)
    api.post(f"/v1/roadmaps/{first}/make-current", headers=learner.headers)

    generate(api, database_dsn, learner, goal)

    versions = api.get(f"/v1/goals/{goal}/roadmaps", headers=learner.headers).json()["items"]
    assert [(v["version"], v["status"]) for v in versions] == [
        (3, "current"),
        (2, "superseded"),
        (1, "superseded"),
    ]


# --- Cleanup ---------------------------------------------------------------------------------


def test_deleting_an_archived_goal_removes_its_roadmaps_and_jobs(
    api: TestClient, database_dsn: str, make_learner: MakeLearner
) -> None:
    learner = make_learner()
    goal, first, _ = two_versions(api, database_dsn, learner)
    api.put(f"/v1/goals/{goal}/status", headers=learner.headers, json={"status": "archived"})

    assert api.delete(f"/v1/goals/{goal}", headers=learner.headers).status_code == 204

    assert api.get(f"/v1/roadmaps/{first}", headers=learner.headers).status_code == 404
    assert (
        admin(database_dsn).scalar(
            "select count(*) from public.roadmaps where goal_id = %s", (UUID(goal),)
        )
        == 0
    )
    assert (
        admin(database_dsn).scalar(
            "select count(*) from public.generation_jobs where goal_id = %s", (UUID(goal),)
        )
        == 0
    )
