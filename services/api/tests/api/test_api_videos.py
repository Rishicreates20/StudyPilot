"""Study videos through the HTTP API: ownership, validation, limits, jobs and what is shown."""

from collections.abc import Callable
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from pydantic import SecretStr

from conftest import Learner
from support.api_helpers import create_goal, generate_roadmap, set_status, topic_ids
from support.database import admin
from support.worker import clear_queue, run_worker_once
from support.youtube import FakeYouTube, video_item

MakeLearner = Callable[..., Learner]
Configure = Callable[..., None]


@pytest.fixture
def youtube_on(configure_app: Configure) -> None:
    """The app as deployed with a YouTube Data API key."""
    configure_app(youtube_api_key=SecretStr("test-youtube-key"))


def videos(api: TestClient, learner: Learner, item_id: str) -> Response:
    return api.get(f"/v1/roadmap-items/{item_id}/videos", headers=learner.headers)


def find(
    api: TestClient,
    learner: Learner,
    item_id: str,
    /,
    *,
    headers: dict[str, str] | None = None,
    **body: Any,
) -> Response:
    return api.post(
        f"/v1/roadmap-items/{item_id}/videos",
        headers={**learner.headers, **(headers or {})},
        json=body,
    )


def run_search(dsn: str, youtube: FakeYouTube) -> None:
    assert run_worker_once(dsn, videos=youtube.client()) is True


def stocked_youtube() -> FakeYouTube:
    youtube = FakeYouTube()
    youtube.add(
        "en",
        *[
            video_item(
                f"vid{n:08d}",
                f"Topic 1 explained, part {n}",
                channel_id=f"UC-{n}",
                channel_title=f"Teacher {n}",
            )
            for n in range(1, 4)
        ],
    )
    return youtube


@pytest.fixture
def owned(api: TestClient, database_dsn: str, make_learner: MakeLearner) -> dict[str, Any]:
    """Alice with a goal and a roadmap; Bob with nothing."""
    alice, bob = make_learner(), make_learner()
    goal = create_goal(api, alice)
    roadmap = generate_roadmap(api, database_dsn, alice, goal["id"])
    topics = topic_ids(roadmap)
    # Topic titles from the built-in roadmap; make the first one predictable for the fake search.
    admin(database_dsn).execute(
        "update public.roadmap_items set title = 'Topic 1' where id = %s", (topics[0],)
    )
    revision = roadmap["revision_sessions"][0]["id"]
    clear_queue(database_dsn)
    return {
        "alice": alice,
        "bob": bob,
        "goal": goal["id"],
        "roadmap": roadmap,
        "item": topics[0],
        "revision": revision,
    }


# --- Authentication and ownership ---------------------------------------------------------------

ENDPOINTS: list[tuple[str, dict[str, Any] | None]] = [("get", None), ("post", {})]


@pytest.mark.parametrize(("method", "body"), ENDPOINTS)
def test_every_endpoint_requires_a_token(
    api: TestClient, owned: dict[str, Any], method: str, body: Any
) -> None:
    url = f"/v1/roadmap-items/{owned['item']}/videos"
    assert api.request(method, url, json=body).status_code == 401


@pytest.mark.parametrize(("method", "body"), ENDPOINTS)
def test_every_endpoint_rejects_a_bad_token(
    api: TestClient, owned: dict[str, Any], method: str, body: Any
) -> None:
    url = f"/v1/roadmap-items/{owned['item']}/videos"
    response = api.request(method, url, json=body, headers={"Authorization": "Bearer nonsense"})
    assert response.status_code == 401


@pytest.mark.usefixtures("youtube_on")
@pytest.mark.parametrize(("method", "body"), ENDPOINTS)
def test_another_learners_topic_is_not_found(
    api: TestClient, owned: dict[str, Any], method: str, body: Any
) -> None:
    url = f"/v1/roadmap-items/{owned['item']}/videos"
    response = api.request(method, url, json=body, headers=owned["bob"].headers)

    assert response.status_code == 404
    assert response.json()["code"] == "TOPIC_NOT_FOUND"


@pytest.mark.usefixtures("youtube_on")
def test_an_unknown_topic_is_not_found(api: TestClient, owned: dict[str, Any]) -> None:
    assert videos(api, owned["alice"], str(uuid4())).status_code == 404
    assert find(api, owned["alice"], str(uuid4())).status_code == 404


@pytest.mark.usefixtures("youtube_on")
def test_a_body_naming_anything_else_is_refused(api: TestClient, owned: dict[str, Any]) -> None:
    response = find(api, owned["alice"], owned["item"], user_id=str(owned["bob"].id))
    assert response.status_code == 422


# --- Not configured -------------------------------------------------------------------------------


def test_without_a_key_nothing_is_queued_and_the_page_says_so(
    api: TestClient, owned: dict[str, Any]
) -> None:
    shown = videos(api, owned["alice"], owned["item"])
    assert shown.status_code == 200
    body = shown.json()
    assert (body["configured"], body["can_search"]) == (False, False)
    assert (body["search"], body["videos"], body["job"]) == (None, [], None)

    response = find(api, owned["alice"], owned["item"])
    assert response.status_code == 503
    assert response.json()["code"] == "VIDEOS_NOT_CONFIGURED"


# --- Finding videos -----------------------------------------------------------------------------


@pytest.mark.usefixtures("youtube_on")
def test_a_search_is_queued_run_and_shown(
    api: TestClient, database_dsn: str, owned: dict[str, Any]
) -> None:
    alice = owned["alice"]
    before = videos(api, alice, owned["item"]).json()
    assert (before["configured"], before["can_search"], before["search"]) == (True, True, None)

    started = find(api, alice, owned["item"])
    assert started.status_code == 202, started.text
    job = started.json()
    assert started.headers["Location"] == f"/v1/jobs/{job['id']}"
    assert (job["job_type"], job["item_id"], job["status"]) == (
        "resources",
        owned["item"],
        "queued",
    )
    assert videos(api, alice, owned["item"]).json()["job"]["id"] == job["id"]

    run_search(database_dsn, stocked_youtube())

    body = videos(api, alice, owned["item"]).json()
    assert body["job"]["status"] == "completed"
    search = body["search"]
    assert search["languages"] == ["en"] and search["result_count"] == 3
    assert search["queries"][0].startswith("Topic 1")
    shown = body["videos"]
    assert [v["position"] for v in shown] == [1, 2, 3]
    first = shown[0]
    assert first["url"] == f"https://www.youtube.com/watch?v={first['video_id']}"
    assert first["channel_title"].startswith("Teacher")
    assert first["duration_seconds"] == 750
    assert sum(first["score_basis"].values()) == first["relevance_score"]
    # Nothing about the search's inner workings beyond what the contract names.
    assert "description" not in first and "user_id" not in first


@pytest.mark.usefixtures("youtube_on")
def test_a_first_search_needs_no_body(api: TestClient, owned: dict[str, Any]) -> None:
    response = api.post(f"/v1/roadmap-items/{owned['item']}/videos", headers=owned["alice"].headers)

    assert response.status_code == 202, response.text
    assert response.json()["job_type"] == "resources"


@pytest.mark.usefixtures("youtube_on")
def test_a_second_request_while_one_runs_is_a_conflict(
    api: TestClient, owned: dict[str, Any]
) -> None:
    assert find(api, owned["alice"], owned["item"]).status_code == 202

    again = find(api, owned["alice"], owned["item"])

    assert again.status_code == 409
    assert again.json()["code"] == "VIDEO_SEARCH_ACTIVE"


@pytest.mark.usefixtures("youtube_on")
def test_the_same_idempotency_key_returns_the_same_job(
    api: TestClient, owned: dict[str, Any]
) -> None:
    key = {"Idempotency-Key": f"videos-{uuid4()}"}
    first = find(api, owned["alice"], owned["item"], headers=key)
    second = find(api, owned["alice"], owned["item"], headers=key)
    different = find(api, owned["alice"], owned["item"], headers=key, refresh=True)

    assert (first.status_code, second.status_code) == (202, 202)
    assert first.json()["id"] == second.json()["id"]
    assert different.status_code == 409
    assert different.json()["code"] == "IDEMPOTENCY_KEY_REUSED"


@pytest.mark.usefixtures("youtube_on")
def test_a_topic_with_suggestions_is_searched_again_only_on_request(
    api: TestClient, database_dsn: str, owned: dict[str, Any]
) -> None:
    alice = owned["alice"]
    assert find(api, alice, owned["item"]).status_code == 202
    run_search(database_dsn, stocked_youtube())

    plain = find(api, alice, owned["item"])
    assert plain.status_code == 409
    assert plain.json()["code"] == "VIDEOS_EXIST"

    refresh = find(api, alice, owned["item"], refresh=True)
    assert refresh.status_code == 202, refresh.text


@pytest.mark.usefixtures("youtube_on")
def test_a_failed_search_can_be_retried(
    api: TestClient, database_dsn: str, owned: dict[str, Any]
) -> None:
    alice = owned["alice"]
    job = find(api, alice, owned["item"]).json()
    admin(database_dsn).execute(
        "update public.generation_jobs set status = 'failed', stage = 'failed',"
        " error_code = 'YOUTUBE_UNAVAILABLE', finished_at = now() where id = %s",
        (job["id"],),
    )

    retried = api.post(f"/v1/jobs/{job['id']}/retry", headers=alice.headers)

    assert retried.status_code == 202, retried.text
    assert retried.json()["job_type"] == "resources"
    assert retried.json()["id"] != job["id"]


# --- Rules ----------------------------------------------------------------------------------------


@pytest.mark.usefixtures("youtube_on")
def test_revision_sessions_have_no_videos(api: TestClient, owned: dict[str, Any]) -> None:
    assert videos(api, owned["alice"], owned["revision"]).status_code == 404
    response = find(api, owned["alice"], owned["revision"])
    assert response.status_code == 422
    assert response.json()["code"] == "TOPIC_HAS_NO_VIDEOS"


@pytest.mark.usefixtures("youtube_on")
def test_an_archived_goal_is_read_only(api: TestClient, owned: dict[str, Any]) -> None:
    set_status(api, owned["alice"], owned["goal"], "archived")

    assert videos(api, owned["alice"], owned["item"]).json()["can_search"] is False
    response = find(api, owned["alice"], owned["item"])
    assert response.status_code == 409
    assert response.json()["code"] == "GOAL_ARCHIVED"


@pytest.mark.usefixtures("youtube_on")
def test_topics_of_an_earlier_roadmap_are_not_searched(
    api: TestClient, database_dsn: str, owned: dict[str, Any]
) -> None:
    admin(database_dsn).execute(
        "update public.roadmaps set status = 'superseded' where id = %s", (owned["roadmap"]["id"],)
    )

    assert videos(api, owned["alice"], owned["item"]).json()["can_search"] is False
    response = find(api, owned["alice"], owned["item"])
    assert response.status_code == 409
    assert response.json()["code"] == "ROADMAP_NOT_CURRENT"


def test_a_learner_has_a_daily_allowance(
    api: TestClient, owned: dict[str, Any], configure_app: Configure
) -> None:
    configure_app(youtube_api_key=SecretStr("test-youtube-key"), video_searches_per_user_per_day=1)
    assert find(api, owned["alice"], owned["item"]).status_code == 202

    other_topic = topic_ids(owned["roadmap"])[1]
    response = find(api, owned["alice"], other_topic)

    assert response.status_code == 429
    assert response.json()["code"] == "VIDEO_SEARCH_LIMIT_REACHED"
