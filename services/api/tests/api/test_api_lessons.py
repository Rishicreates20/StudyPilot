"""Lessons and study progress through the HTTP API: ownership, validation, jobs and versions."""

from collections.abc import Callable
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from psycopg import sql

from conftest import Learner
from support.api_helpers import create_goal, generate_roadmap, set_status, topic_ids
from support.database import admin
from support.worker import clear_queue, run_worker_once

MakeLearner = Callable[..., Learner]


def start(
    api: TestClient,
    learner: Learner,
    item_id: str,
    /,
    *,
    headers: dict[str, str] | None = None,
    **body: Any,
) -> Response:
    return api.post(
        f"/v1/roadmap-items/{item_id}/lessons",
        headers={**learner.headers, **(headers or {})},
        json=body,
    )


def write(
    api: TestClient, dsn: str, learner: Learner, item_id: str, /, **body: Any
) -> dict[str, Any]:
    """Start a lesson and run it to completion with the real worker. Returns the finished job."""
    clear_queue(dsn)  # leftovers from other tests must not be picked up instead of this job
    response = start(api, learner, item_id, **body)
    assert response.status_code == 202, response.text
    assert run_worker_once(dsn) is True
    job = api.get(f"/v1/jobs/{response.json()['id']}", headers=learner.headers).json()
    assert job["status"] == "completed", job
    return job


def study(api: TestClient, learner: Learner, item_id: str, **params: str) -> Response:
    return api.get(f"/v1/roadmap-items/{item_id}/study", headers=learner.headers, params=params)


def save_progress(api: TestClient, learner: Learner, lesson_id: str, **body: Any) -> Response:
    return api.put(f"/v1/lessons/{lesson_id}/progress", headers=learner.headers, json=body)


def item_of(roadmap: dict[str, Any], kind: str) -> str:
    items = [*roadmap["revision_sessions"], *roadmap["enrichment"]]
    return next(item["id"] for item in items if item["kind"] == kind)


@pytest.fixture
def owned(api: TestClient, database_dsn: str, make_learner: MakeLearner) -> dict[str, Any]:
    """Alice with a goal, a roadmap and a written lesson for its first topic; Bob with nothing."""
    alice, bob = make_learner(), make_learner()
    goal = create_goal(api, alice)
    roadmap = generate_roadmap(api, database_dsn, alice, goal["id"])
    topics = topic_ids(roadmap)
    job = write(api, database_dsn, alice, topics[0])
    return {
        "alice": alice,
        "bob": bob,
        "goal": goal["id"],
        "roadmap": roadmap,
        "topics": topics,
        "item": topics[0],
        "job": job["id"],
        "lesson": job["lesson_id"],
    }


@pytest.fixture
def fresh(api: TestClient, database_dsn: str, make_learner: MakeLearner) -> dict[str, Any]:
    """Alice with a goal and a roadmap but no lessons yet."""
    alice = make_learner()
    goal = create_goal(api, alice)
    roadmap = generate_roadmap(api, database_dsn, alice, goal["id"])
    return {"alice": alice, "goal": goal["id"], "roadmap": roadmap, "topics": topic_ids(roadmap)}


# --- Authentication and ownership on every endpoint ------------------------------------------

ENDPOINTS: list[tuple[str, str, dict[str, Any] | None]] = [
    ("post", "/v1/roadmap-items/{item}/lessons", {"regenerate": True}),
    ("get", "/v1/roadmap-items/{item}/study", None),
    ("put", "/v1/lessons/{lesson}/progress", {"completed_section_ids": []}),
]


def url_for(template: str, owned: dict[str, Any]) -> str:
    return template.format(item=owned["item"], lesson=owned["lesson"])


@pytest.mark.parametrize(("method", "template", "body"), ENDPOINTS)
def test_every_endpoint_requires_a_token(
    api: TestClient, owned: dict[str, Any], method: str, template: str, body: Any
) -> None:
    assert api.request(method, url_for(template, owned), json=body).status_code == 401


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
    missing = {"item": str(uuid4()), "lesson": str(uuid4())}
    theirs = api.request(method, url_for(template, owned), json=body, headers=owned["bob"].headers)
    nothing = api.request(
        method, template.format(**missing), json=body, headers=owned["alice"].headers
    )

    assert (nothing.status_code, nothing.json()["code"]) == (
        theirs.status_code,
        theirs.json()["code"],
    )


def test_another_learner_cannot_start_a_lesson_for_my_topic_and_nothing_is_queued(
    api: TestClient, database_dsn: str, fresh: dict[str, Any], make_learner: MakeLearner
) -> None:
    bob = make_learner()

    response = start(api, bob, fresh["topics"][0])

    assert response.status_code == 404
    assert (
        admin(database_dsn).scalar(
            "select count(*) from public.generation_jobs where item_id = %s", (fresh["topics"][0],)
        )
        == 0
    )


def test_a_malformed_id_is_a_validation_error_not_a_crash(
    api: TestClient, make_learner: MakeLearner
) -> None:
    learner = make_learner()

    assert api.get("/v1/roadmap-items/nope/study", headers=learner.headers).status_code == 422
    assert start(api, learner, "12345").status_code == 422
    assert save_progress(api, learner, "nope").status_code == 422
    assert study(api, learner, str(uuid4()), lesson_id="nope").status_code == 422


# --- Starting a lesson -----------------------------------------------------------------------


def test_starting_queues_a_job_and_returns_at_once(
    api: TestClient, database_dsn: str, fresh: dict[str, Any]
) -> None:
    item = fresh["topics"][0]

    response = start(api, fresh["alice"], item)

    assert response.status_code == 202
    job = response.json()
    assert response.headers["location"] == f"/v1/jobs/{job['id']}"
    assert (job["status"], job["stage"], job["progress"], job["attempts"]) == (
        "queued",
        "queued",
        0,
        0,
    )
    assert (job["job_type"], job["item_id"], job["goal_id"]) == ("lesson", item, fresh["goal"])
    assert job["lesson_id"] is None and job["roadmap_id"] is None
    row = admin(database_dsn).fetchone(
        "select user_id, request from public.generation_jobs where id = %s", (job["id"],)
    )
    assert row == {"user_id": fresh["alice"].id, "request": {}}


@pytest.mark.parametrize(
    "body",
    [
        {"user_id": str(uuid4())},
        {"status": "completed"},
        {"item_id": str(uuid4())},
        {"goal_id": str(uuid4())},
        {"feedback": "x" * 301},
        {"feedback": 42},
        {"adjust": "angrier"},
        {"regenerate": "sometimes"},
    ],
)
def test_unknown_or_oversized_fields_are_rejected(
    api: TestClient, fresh: dict[str, Any], body: dict[str, Any]
) -> None:
    response = start(api, fresh["alice"], fresh["topics"][0], **body)

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_blank_feedback_changes_nothing_about_the_request(
    api: TestClient, database_dsn: str, fresh: dict[str, Any]
) -> None:
    job = start(api, fresh["alice"], fresh["topics"][0], feedback="   ").json()

    assert (
        admin(database_dsn).scalar(
            "select request from public.generation_jobs where id = %s", (job["id"],)
        )
        == {}
    )


def test_a_lesson_cannot_be_started_without_an_ai_provider(
    api: TestClient, database_dsn: str, fresh: dict[str, Any], no_ai: None
) -> None:
    response = start(api, fresh["alice"], fresh["topics"][0])

    assert response.status_code == 503
    assert response.json()["code"] == "AI_NOT_CONFIGURED"
    assert (
        admin(database_dsn).scalar(
            "select count(*) from public.generation_jobs where item_id = %s",
            (fresh["topics"][0],),
        )
        == 0
    )


def test_a_revision_session_has_no_lesson(
    api: TestClient, database_dsn: str, fresh: dict[str, Any]
) -> None:
    revision = item_of(fresh["roadmap"], "revision")

    response = start(api, fresh["alice"], revision)

    assert response.status_code == 422
    assert response.json()["code"] == "TOPIC_NOT_LESSONABLE"
    assert study(api, fresh["alice"], revision).status_code == 404


def test_an_optional_extra_can_have_a_lesson(
    api: TestClient, database_dsn: str, fresh: dict[str, Any]
) -> None:
    extra = item_of(fresh["roadmap"], "enrichment")

    job = write(api, database_dsn, fresh["alice"], extra)

    assert job["status"] == "completed"
    assert any(
        entry["kind"] == "enrichment"
        for entry in study(api, fresh["alice"], extra).json()["outline"]
    )


def test_a_second_lesson_for_a_topic_already_being_written_is_refused(
    api: TestClient, fresh: dict[str, Any]
) -> None:
    first = start(api, fresh["alice"], fresh["topics"][0])
    second = start(api, fresh["alice"], fresh["topics"][0])

    assert first.status_code == 202
    assert second.status_code == 409 and second.json()["code"] == "LESSON_JOB_ACTIVE"


def test_two_topics_can_be_written_at_once_up_to_the_cap(
    api: TestClient, fresh: dict[str, Any], configure_app: Callable[..., None]
) -> None:
    configure_app(lesson_jobs_active_per_user=2)
    topics = fresh["topics"]

    assert start(api, fresh["alice"], topics[0]).status_code == 202
    assert start(api, fresh["alice"], topics[1]).status_code == 202
    third = start(api, fresh["alice"], topics[2])

    assert third.status_code == 429 and third.json()["code"] == "LESSON_QUEUE_FULL"


def test_the_cap_is_per_learner(
    api: TestClient,
    database_dsn: str,
    fresh: dict[str, Any],
    make_learner: MakeLearner,
    configure_app: Callable[..., None],
) -> None:
    configure_app(lesson_jobs_active_per_user=1)
    other = make_learner()
    other_roadmap = generate_roadmap(api, database_dsn, other, create_goal(api, other)["id"])

    assert start(api, fresh["alice"], fresh["topics"][0]).status_code == 202
    assert start(api, other, topic_ids(other_roadmap)[0]).status_code == 202


def test_the_daily_allowance_stops_a_runaway(
    api: TestClient,
    database_dsn: str,
    fresh: dict[str, Any],
    configure_app: Callable[..., None],
) -> None:
    configure_app(lesson_jobs_per_user_per_day=1)
    write(api, database_dsn, fresh["alice"], fresh["topics"][0])

    response = start(api, fresh["alice"], fresh["topics"][1])

    assert response.status_code == 429
    assert response.json()["code"] == "LESSON_LIMIT_REACHED"
    assert "tomorrow" in response.json()["detail"]


def test_roadmap_generations_do_not_use_up_the_lesson_allowance(
    api: TestClient,
    database_dsn: str,
    fresh: dict[str, Any],
    configure_app: Callable[..., None],
) -> None:
    configure_app(lesson_jobs_per_user_per_day=1)

    assert start(api, fresh["alice"], fresh["topics"][0]).status_code == 202


def test_a_lesson_job_does_not_block_a_roadmap_revision_of_the_same_goal(
    api: TestClient, fresh: dict[str, Any]
) -> None:
    assert start(api, fresh["alice"], fresh["topics"][0]).status_code == 202

    revision = api.post(
        f"/v1/goals/{fresh['goal']}/roadmaps", headers=fresh["alice"].headers, json={}
    )

    assert revision.status_code == 202


def test_a_topic_that_already_has_a_lesson_is_not_started_again_by_accident(
    api: TestClient, owned: dict[str, Any]
) -> None:
    response = start(api, owned["alice"], owned["item"])

    assert response.status_code == 409 and response.json()["code"] == "LESSON_EXISTS"


@pytest.mark.parametrize("body", [{"regenerate": True}, {"adjust": "simpler"}, {"feedback": "x"}])
def test_asking_for_a_change_starts_a_new_version_even_though_a_lesson_exists(
    api: TestClient, database_dsn: str, owned: dict[str, Any], body: dict[str, Any]
) -> None:
    response = start(api, owned["alice"], owned["item"], **body)

    assert response.status_code == 202
    request = admin(database_dsn).scalar(
        "select request from public.generation_jobs where id = %s", (response.json()["id"],)
    )
    assert request["regenerate"] is True
    assert request["base_lesson_id"] == owned["lesson"]
    for key, value in body.items():
        assert request[key] == value


def test_a_goal_that_is_archived_is_read_only(api: TestClient, fresh: dict[str, Any]) -> None:
    set_status(api, fresh["alice"], fresh["goal"], "archived")

    response = start(api, fresh["alice"], fresh["topics"][0])

    assert response.status_code == 409 and response.json()["code"] == "GOAL_ARCHIVED"


def test_a_topic_of_an_earlier_roadmap_version_cannot_get_a_new_lesson(
    api: TestClient, database_dsn: str, fresh: dict[str, Any]
) -> None:
    old_topic = fresh["topics"][0]
    generate_roadmap(api, database_dsn, fresh["alice"], fresh["goal"])  # version 2 is current

    response = start(api, fresh["alice"], old_topic)

    assert response.status_code == 409 and response.json()["code"] == "ROADMAP_NOT_CURRENT"
    assert study(api, fresh["alice"], old_topic).json()["can_generate"] is False


# --- Idempotency -----------------------------------------------------------------------------


def test_the_same_idempotency_key_returns_the_same_job(
    api: TestClient, database_dsn: str, fresh: dict[str, Any]
) -> None:
    headers = {"Idempotency-Key": "form-submission-1"}
    first = start(api, fresh["alice"], fresh["topics"][0], headers=headers)
    second = start(api, fresh["alice"], fresh["topics"][0], headers=headers)

    assert second.status_code == 202
    assert second.json()["id"] == first.json()["id"]
    assert (
        admin(database_dsn).scalar(
            "select count(*) from public.generation_jobs where item_id = %s", (fresh["topics"][0],)
        )
        == 1
    )


def test_an_idempotency_key_cannot_be_reused_for_something_else(
    api: TestClient, fresh: dict[str, Any]
) -> None:
    headers = {"Idempotency-Key": "form-submission-2"}
    start(api, fresh["alice"], fresh["topics"][0], headers=headers)

    other_topic = start(api, fresh["alice"], fresh["topics"][1], headers=headers)
    other_body = start(api, fresh["alice"], fresh["topics"][0], headers=headers, adjust="deeper")

    assert other_topic.status_code == 409
    assert other_topic.json()["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert other_body.status_code == 409


def test_a_key_used_for_a_roadmap_cannot_return_a_roadmap_job_as_a_lesson(
    api: TestClient, fresh: dict[str, Any]
) -> None:
    headers = {"Idempotency-Key": "shared-key-1234"}
    roadmap = api.post(
        f"/v1/goals/{fresh['goal']}/roadmaps",
        headers={**fresh["alice"].headers, **headers},
        json={},
    )
    assert roadmap.status_code == 202

    lesson = start(api, fresh["alice"], fresh["topics"][0], headers=headers)
    roadmap_again = api.post(
        f"/v1/goals/{fresh['goal']}/roadmaps",
        headers={**fresh["alice"].headers, **headers},
        json={},
    )

    assert lesson.status_code == 409 and lesson.json()["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert roadmap_again.json()["id"] == roadmap.json()["id"]


# --- The study view --------------------------------------------------------------------------


def test_before_a_lesson_exists_the_study_view_says_so_and_offers_to_write_one(
    api: TestClient, fresh: dict[str, Any]
) -> None:
    topics = fresh["topics"]

    view = study(api, fresh["alice"], topics[1]).json()

    assert view["lesson"] is None and view["progress"] is None and view["job"] is None
    assert view["versions"] == []
    assert view["can_generate"] is True and view["goal_archived"] is False
    assert view["topic"]["id"] == topics[1] and view["topic"]["kind"] == "topic"
    assert view["topic"]["practice_task"] and view["topic"]["module_title"]
    assert view["roadmap"]["status"] == "current" and view["roadmap"]["version"] == 1
    assert view["previous"]["id"] == topics[0] and view["next"]["id"] == topics[2]


def test_the_first_and_last_topics_have_one_neighbour(
    api: TestClient, fresh: dict[str, Any]
) -> None:
    topics = fresh["topics"]

    first = study(api, fresh["alice"], topics[0]).json()
    extra = study(api, fresh["alice"], item_of(fresh["roadmap"], "enrichment")).json()

    assert first["previous"] is None and first["next"]["id"] == topics[1]
    assert extra["next"] is None and extra["previous"]["id"] == topics[-1]


def test_the_contents_list_the_topics_in_study_order_without_revision_sessions(
    api: TestClient, fresh: dict[str, Any]
) -> None:
    view = study(api, fresh["alice"], fresh["topics"][0]).json()

    ids = [entry["item_id"] for entry in view["outline"]]
    assert ids[: len(fresh["topics"])] == fresh["topics"]
    assert {entry["kind"] for entry in view["outline"]} == {"topic", "enrichment"}
    assert all(entry["study"]["status"] == "not_started" for entry in view["outline"])
    assert all(entry["study"]["has_lesson"] is False for entry in view["outline"])


def test_a_written_lesson_is_returned_as_a_typed_document(
    api: TestClient, owned: dict[str, Any]
) -> None:
    view = study(api, owned["alice"], owned["item"]).json()

    lesson = view["lesson"]
    assert lesson["id"] == owned["lesson"] and lesson["status"] == "current"
    assert lesson["version"] == 1 and lesson["content_version"] == 1
    assert lesson["is_synthetic"] is True and lesson["provider"] == "fake"
    assert lesson["prompt_version"] == "lesson-writer/v2"
    content = lesson["content"]
    assert content["title"] == lesson["title"] and content["language"] == "en"
    assert [s["id"] for s in content["sections"]] == [
        f"s{n}" for n in range(1, len(content["sections"]) + 1)
    ]
    block_types = {b["type"] for s in content["sections"] for b in s["blocks"]}
    assert block_types == {"paragraph", "list", "code", "callout"}
    for key in (
        "learning_objectives", "definitions", "worked_examples", "common_misconceptions",
        "summary", "simple_explanation", "source_references",
    ):  # fmt: skip
        assert key in content
    assert content["source_references"] == []  # nothing was supplied, so nothing is cited
    assert [v["id"] for v in view["versions"]] == [owned["lesson"]]
    assert view["job"]["status"] == "completed" and view["job"]["lesson_id"] == owned["lesson"]


def test_the_response_exposes_no_prompts_or_job_internals(
    api: TestClient, owned: dict[str, Any]
) -> None:
    body = study(api, owned["alice"], owned["item"]).text

    for forbidden in ("checkpoint", '"request"', "system_prompt", "locked_by", "learner_data"):
        assert forbidden not in body


def test_an_earlier_version_can_still_be_opened(
    api: TestClient, database_dsn: str, owned: dict[str, Any]
) -> None:
    write(api, database_dsn, owned["alice"], owned["item"], adjust="simpler")

    current = study(api, owned["alice"], owned["item"]).json()
    earlier = study(api, owned["alice"], owned["item"], lesson_id=owned["lesson"]).json()

    assert current["lesson"]["version"] == 2 and current["lesson"]["adjust"] == "simpler"
    assert current["lesson"]["based_on_lesson_id"] == owned["lesson"]
    assert (
        earlier["lesson"]["id"] == owned["lesson"] and earlier["lesson"]["status"] == "superseded"
    )
    assert [v["version"] for v in current["versions"]] == [2, 1]


def test_asking_for_a_lesson_that_is_not_this_topics_is_a_404(
    api: TestClient, database_dsn: str, owned: dict[str, Any]
) -> None:
    other_topic_job = write(api, database_dsn, owned["alice"], owned["topics"][1])
    for lesson_id in (str(uuid4()), other_topic_job["lesson_id"]):
        response = study(api, owned["alice"], owned["item"], lesson_id=lesson_id)

        assert response.status_code == 404 and response.json()["code"] == "LESSON_NOT_FOUND"


def test_another_learners_lesson_id_is_a_404_too(api: TestClient, owned: dict[str, Any]) -> None:
    response = study(api, owned["bob"], owned["item"], lesson_id=owned["lesson"])

    assert response.status_code == 404


def test_a_failed_lesson_is_reported_with_a_reason_the_learner_can_read(
    api: TestClient, database_dsn: str, fresh: dict[str, Any]
) -> None:
    job = start(api, fresh["alice"], fresh["topics"][0]).json()
    admin(database_dsn).execute(
        "update public.generation_jobs set status = 'failed', stage = 'failed',"
        " finished_at = now(), error_code = 'LESSON_INVALID',"
        " error_message = 'The AI could not.' where id = %s",
        (job["id"],),
    )

    view = study(api, fresh["alice"], fresh["topics"][0]).json()

    assert view["lesson"] is None
    assert (view["job"]["status"], view["job"]["error_code"]) == ("failed", "LESSON_INVALID")
    assert view["job"]["error_message"] == "The AI could not."


def test_the_study_view_of_an_archived_goal_can_be_read_but_not_extended(
    api: TestClient, owned: dict[str, Any]
) -> None:
    set_status(api, owned["alice"], owned["goal"], "archived")

    view = study(api, owned["alice"], owned["item"]).json()

    assert view["goal_archived"] is True and view["can_generate"] is False
    assert view["lesson"] is not None


# --- Progress --------------------------------------------------------------------------------


def section_ids(api: TestClient, owned: dict[str, Any]) -> list[str]:
    lesson = study(api, owned["alice"], owned["item"]).json()["lesson"]
    return [s["id"] for s in lesson["content"]["sections"]]


def test_saving_progress_records_where_to_resume(api: TestClient, owned: dict[str, Any]) -> None:
    sections = section_ids(api, owned)

    response = save_progress(
        api, owned["alice"], owned["lesson"],
        completed_section_ids=[sections[0]], current_section_id=sections[1],
    )  # fmt: skip

    assert response.status_code == 200
    saved = response.json()
    assert saved["lesson_id"] == owned["lesson"] and saved["status"] == "in_progress"
    assert saved["completed_section_ids"] == [sections[0]]
    assert saved["current_section_id"] == sections[1] and saved["completed_at"] is None
    view = study(api, owned["alice"], owned["item"]).json()
    assert view["progress"] == saved  # resuming later shows the same place


def test_progress_is_replaced_not_merged(api: TestClient, owned: dict[str, Any]) -> None:
    sections = section_ids(api, owned)
    save_progress(api, owned["alice"], owned["lesson"], completed_section_ids=sections[:2])

    saved = save_progress(
        api, owned["alice"], owned["lesson"], completed_section_ids=[sections[2]]
    ).json()

    assert saved["completed_section_ids"] == [sections[2]]
    assert saved["current_section_id"] is None


def test_sections_are_kept_in_the_lessons_order(api: TestClient, owned: dict[str, Any]) -> None:
    sections = section_ids(api, owned)

    saved = save_progress(
        api, owned["alice"], owned["lesson"], completed_section_ids=[sections[2], sections[0]]
    ).json()

    assert saved["completed_section_ids"] == [sections[0], sections[2]]


def test_finishing_marks_every_section_done_and_records_when(
    api: TestClient, owned: dict[str, Any]
) -> None:
    sections = section_ids(api, owned)

    saved = save_progress(api, owned["alice"], owned["lesson"], completed=True).json()

    assert saved["status"] == "completed" and saved["completed_at"] is not None
    assert saved["completed_section_ids"] == sections


def test_finishing_again_keeps_the_original_completion_time(
    api: TestClient, owned: dict[str, Any]
) -> None:
    first = save_progress(api, owned["alice"], owned["lesson"], completed=True).json()
    second = save_progress(api, owned["alice"], owned["lesson"], completed=True).json()

    assert second["completed_at"] == first["completed_at"]


def test_a_finished_lesson_can_be_reopened(api: TestClient, owned: dict[str, Any]) -> None:
    sections = section_ids(api, owned)
    save_progress(api, owned["alice"], owned["lesson"], completed=True)

    saved = save_progress(
        api, owned["alice"], owned["lesson"], completed_section_ids=sections[:1]
    ).json()

    assert saved["status"] == "in_progress" and saved["completed_at"] is None


@pytest.mark.parametrize(
    "body",
    [
        {"completed_section_ids": ["s99"]},
        {"completed_section_ids": ["s1", "s1"]},
        {"current_section_id": "s99"},
    ],
)
def test_progress_can_only_name_the_lessons_own_sections(
    api: TestClient, owned: dict[str, Any], body: dict[str, Any]
) -> None:
    response = save_progress(api, owned["alice"], owned["lesson"], **body)

    assert response.status_code == 422
    assert response.json()["code"] == "UNKNOWN_SECTION"


@pytest.mark.parametrize(
    "body",
    [
        {"user_id": str(uuid4())},
        {"status": "completed"},
        {"current_section_id": "intro"},
        {"completed_section_ids": "s1"},
        {"completed_section_ids": [f"s{n}" for n in range(1, 20)]},
    ],
)
def test_malformed_progress_is_rejected(
    api: TestClient, owned: dict[str, Any], body: dict[str, Any]
) -> None:
    response = save_progress(api, owned["alice"], owned["lesson"], **body)

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_progress_cannot_be_saved_for_another_learners_lesson(
    api: TestClient, database_dsn: str, owned: dict[str, Any]
) -> None:
    response = save_progress(api, owned["bob"], owned["lesson"], completed=True)

    assert response.status_code == 404
    assert (
        admin(database_dsn).scalar(
            "select count(*) from public.lesson_progress where lesson_id = %s", (owned["lesson"],)
        )
        == 0
    )


def test_progress_is_read_only_on_an_archived_goal(api: TestClient, owned: dict[str, Any]) -> None:
    set_status(api, owned["alice"], owned["goal"], "archived")

    response = save_progress(api, owned["alice"], owned["lesson"], completed=True)

    assert response.status_code == 409 and response.json()["code"] == "GOAL_ARCHIVED"


def test_each_version_keeps_its_own_progress(
    api: TestClient, database_dsn: str, owned: dict[str, Any]
) -> None:
    save_progress(api, owned["alice"], owned["lesson"], completed=True)
    newer = write(api, database_dsn, owned["alice"], owned["item"], adjust="simpler")

    view = study(api, owned["alice"], owned["item"]).json()
    older = study(api, owned["alice"], owned["item"], lesson_id=owned["lesson"]).json()

    assert view["lesson"]["id"] == newer["lesson_id"] and view["progress"] is None
    assert older["progress"]["status"] == "completed"


def test_the_roadmap_shows_each_topics_study_state_and_the_completed_count(
    api: TestClient, database_dsn: str, owned: dict[str, Any]
) -> None:
    sections = section_ids(api, owned)
    second = write(api, database_dsn, owned["alice"], owned["topics"][1])["lesson_id"]
    save_progress(api, owned["alice"], owned["lesson"], completed=True)
    save_progress(api, owned["alice"], second, completed_section_ids=sections[:1])

    roadmap = api.get(
        f"/v1/roadmaps/{owned['roadmap']['id']}", headers=owned["alice"].headers
    ).json()

    topics = {t["id"]: t["study"] for m in roadmap["modules"] for t in m["topics"]}
    assert topics[owned["topics"][0]]["status"] == "completed"
    assert (
        topics[owned["topics"][0]]["sections_done"] == topics[owned["topics"][0]]["sections_total"]
    )
    assert topics[owned["topics"][1]]["status"] == "in_progress"
    assert topics[owned["topics"][1]]["sections_done"] == 1
    assert topics[owned["topics"][2]] == {
        "status": "not_started", "has_lesson": False, "sections_done": 0, "sections_total": 0,
    }  # fmt: skip
    assert roadmap["completed_topics"] == 1
    versions = api.get(f"/v1/goals/{owned['goal']}/roadmaps", headers=owned["alice"].headers).json()
    assert versions["items"][0]["completed_topics"] == 1


def test_revision_sessions_show_no_study_state(api: TestClient, owned: dict[str, Any]) -> None:
    roadmap = owned["roadmap"]

    revision = roadmap["revision_sessions"][0]

    assert revision["study"]["has_lesson"] is False
    assert revision["study"]["status"] == "not_started"


# --- Jobs: cancel, retry, and keeping lesson jobs apart from roadmap jobs --------------------


def test_a_lesson_job_can_be_cancelled_and_nothing_is_stored(
    api: TestClient, database_dsn: str, fresh: dict[str, Any]
) -> None:
    clear_queue(database_dsn)
    job = start(api, fresh["alice"], fresh["topics"][0]).json()

    cancelled = api.post(f"/v1/jobs/{job['id']}/cancel", headers=fresh["alice"].headers)

    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    assert run_worker_once(database_dsn) is False  # nothing left to do
    assert study(api, fresh["alice"], fresh["topics"][0]).json()["lesson"] is None


def test_a_failed_lesson_can_be_retried_and_keeps_what_was_asked(
    api: TestClient, database_dsn: str, owned: dict[str, Any]
) -> None:
    failed = start(api, owned["alice"], owned["item"], adjust="more_examples").json()
    admin(database_dsn).execute(
        "update public.generation_jobs set status = 'failed', stage = 'failed',"
        " finished_at = now(), error_code = 'LESSON_INVALID' where id = %s",
        (failed["id"],),
    )

    retry = api.post(f"/v1/jobs/{failed['id']}/retry", headers=owned["alice"].headers)

    assert retry.status_code == 202
    again = retry.json()
    assert again["id"] != failed["id"]
    assert (again["job_type"], again["item_id"]) == ("lesson", owned["item"])
    request = admin(database_dsn).scalar(
        "select request from public.generation_jobs where id = %s", (again["id"],)
    )
    assert request["adjust"] == "more_examples" and request["regenerate"] is True


def test_a_lesson_job_that_has_not_failed_cannot_be_retried(
    api: TestClient, fresh: dict[str, Any]
) -> None:
    job = start(api, fresh["alice"], fresh["topics"][0]).json()

    response = api.post(f"/v1/jobs/{job['id']}/retry", headers=fresh["alice"].headers)

    assert response.status_code == 409 and response.json()["code"] == "JOB_NOT_RETRYABLE"


def test_another_learner_cannot_cancel_or_retry_my_lesson_job(
    api: TestClient, fresh: dict[str, Any], make_learner: MakeLearner
) -> None:
    job = start(api, fresh["alice"], fresh["topics"][0]).json()
    bob = make_learner()

    assert api.post(f"/v1/jobs/{job['id']}/cancel", headers=bob.headers).status_code == 404
    assert api.post(f"/v1/jobs/{job['id']}/retry", headers=bob.headers).status_code == 404
    assert api.get(f"/v1/jobs/{job['id']}", headers=bob.headers).status_code == 404


def test_the_goals_job_list_only_shows_roadmap_jobs(api: TestClient, fresh: dict[str, Any]) -> None:
    start(api, fresh["alice"], fresh["topics"][0])

    jobs = api.get(f"/v1/goals/{fresh['goal']}/jobs", headers=fresh["alice"].headers).json()

    assert {job["job_type"] for job in jobs["items"]} == {"roadmap"}


def test_finished_lessons_and_progress_disappear_with_the_goal(
    api: TestClient, database_dsn: str, owned: dict[str, Any]
) -> None:
    save_progress(api, owned["alice"], owned["lesson"], completed=True)
    set_status(api, owned["alice"], owned["goal"], "archived")

    deleted = api.delete(f"/v1/goals/{owned['goal']}", headers=owned["alice"].headers)

    assert deleted.status_code == 204
    for table in ("lessons", "lesson_progress"):
        remaining = admin(database_dsn).scalar(
            sql.SQL("select count(*) from public.{} where user_id = %s").format(
                sql.Identifier(table)
            ),
            (owned["alice"].id,),
        )
        assert remaining == 0, table
