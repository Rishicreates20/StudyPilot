"""Learning goals over HTTP: creation, ownership, validation, pagination and limits."""

import uuid
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.schemas.goals import today_utc
from conftest import Learner
from support.database import admin

MakeLearner = Callable[..., Learner]


def create(api: TestClient, learner: Learner, **fields: Any) -> dict[str, Any]:
    response = api.post(
        "/v1/goals", headers=learner.headers, json={"title": "Learn Kubernetes", **fields}
    )
    assert response.status_code == 201, response.text
    return response.json()


def archive(dsn: str, goal_id: str) -> None:
    """Archiving has no endpoint yet; do it as the database owner to test list behaviour."""
    admin(dsn).execute(
        "update public.learning_goals set status = 'archived' where id = %s", (goal_id,)
    )


# --- Creating and reading --------------------------------------------------------------------


def test_creating_a_goal_with_only_a_title_applies_safe_defaults(
    api: TestClient, make_learner: MakeLearner
) -> None:
    learner = make_learner()

    response = api.post("/v1/goals", headers=learner.headers, json={"title": "  Learn Docker  "})
    goal = response.json()

    assert response.status_code == 201
    assert response.headers["location"] == f"/v1/goals/{goal['id']}"
    assert goal["title"] == "Learn Docker"  # trimmed
    assert goal["status"] == "active"
    assert goal["current_level"] == "unknown"  # never a guessed level
    assert goal["goal_type"] == "general"
    assert goal["daily_minutes"] == 60
    assert goal["preferred_languages"] == ["en"]
    assert goal["description"] is None
    assert goal["target_date"] is None
    assert "user_id" not in goal


def test_a_fully_specified_goal_is_stored_and_returned(
    api: TestClient, make_learner: MakeLearner
) -> None:
    learner = make_learner()
    target = (today_utc() + timedelta(days=30)).isoformat()

    goal = create(
        api,
        learner,
        description="Get ready for interviews",
        goal_type="interview",
        current_level="beginner",
        target_date=target,
        daily_minutes=90,
        preferred_languages=["en", "hi", "en"],  # duplicates are dropped
    )

    assert goal["description"] == "Get ready for interviews"
    assert goal["goal_type"] == "interview"
    assert goal["current_level"] == "beginner"
    assert goal["target_date"] == target
    assert goal["daily_minutes"] == 90
    assert goal["preferred_languages"] == ["en", "hi"]


def test_a_created_goal_is_owned_by_the_token_and_can_be_read_back(
    api: TestClient, make_learner: MakeLearner, database_dsn: str
) -> None:
    learner = make_learner()
    goal = create(api, learner)

    fetched = api.get(f"/v1/goals/{goal['id']}", headers=learner.headers)

    assert fetched.status_code == 200
    assert fetched.json() == goal
    owner = admin(database_dsn).scalar(
        "select user_id from public.learning_goals where id = %s", (goal["id"],)
    )
    assert owner == learner.id


def test_a_blank_description_is_stored_as_null(api: TestClient, make_learner: MakeLearner) -> None:
    goal = create(api, make_learner(), description="   ")

    assert goal["description"] is None


# --- Ownership: the browser cannot choose or reach someone else's data -----------------------


def test_a_request_body_cannot_name_the_owner(
    api: TestClient, make_learner: MakeLearner, database_dsn: str
) -> None:
    attacker, victim = make_learner(), make_learner()

    response = api.post(
        "/v1/goals",
        headers=attacker.headers,
        json={"title": "Planted goal", "user_id": str(victim.id)},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    planted = admin(database_dsn).scalar(
        "select count(*) from public.learning_goals where user_id in (%s, %s)",
        (attacker.id, victim.id),
    )
    assert planted == 0


def test_one_users_goal_is_invisible_to_another_user(
    api: TestClient, make_learner: MakeLearner
) -> None:
    alice, bob = make_learner(), make_learner()
    goal = create(api, alice, title="Alice's private goal")

    by_id = api.get(f"/v1/goals/{goal['id']}", headers=bob.headers)
    listing = api.get("/v1/goals", headers=bob.headers)

    assert by_id.status_code == 404
    assert by_id.json()["code"] == "GOAL_NOT_FOUND"
    assert listing.json() == {"items": [], "next_cursor": None}


def test_a_foreign_goal_is_indistinguishable_from_a_missing_one(
    api: TestClient, make_learner: MakeLearner
) -> None:
    """If the answers differed, goal IDs could be probed to learn which exist."""
    alice, bob = make_learner(), make_learner()
    goal = create(api, alice)

    foreign = api.get(f"/v1/goals/{goal['id']}", headers=bob.headers)
    missing = api.get(f"/v1/goals/{uuid.uuid4()}", headers=bob.headers)

    assert foreign.status_code == missing.status_code == 404
    foreign_body: dict[str, Any] = foreign.json()
    missing_body: dict[str, Any] = missing.json()
    foreign_body.pop("request_id")
    missing_body.pop("request_id")
    assert foreign_body == missing_body


def test_listing_never_includes_other_users_goals(
    api: TestClient, make_learner: MakeLearner
) -> None:
    alice, bob = make_learner(), make_learner()
    mine = create(api, alice, title="Mine")
    create(api, bob, title="Bob's")
    create(api, bob, title="Bob's second")

    titles = [item["title"] for item in api.get("/v1/goals", headers=alice.headers).json()["items"]]

    assert titles == [mine["title"]]


def test_a_forged_cursor_cannot_reach_another_users_rows(
    api: TestClient, make_learner: MakeLearner
) -> None:
    from datetime import UTC, datetime

    from app.core.pagination import encode_cursor

    alice, bob = make_learner(), make_learner()
    create(api, alice, title="Alice 1")
    bobs = create(api, bob, title="Bob 1")
    # A cursor positioned just after Bob's goal, replayed by Alice.
    forged = encode_cursor(datetime(2100, 1, 1, tzinfo=UTC), uuid.UUID(bobs["id"]))

    page = api.get("/v1/goals", headers=alice.headers, params={"cursor": forged}).json()

    assert [item["title"] for item in page["items"]] == ["Alice 1"]


# --- Validation ------------------------------------------------------------------------------


def error_fields(response: Any) -> set[str]:
    return {error["field"] for error in response.json()["errors"]}


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({}, "body.title"),
        ({"title": ""}, "body.title"),
        ({"title": "   "}, "body.title"),
        ({"title": "t" * 201}, "body.title"),
        ({"title": "x", "description": "d" * 2001}, "body.description"),
        ({"title": "x", "goal_type": "hobby"}, "body.goal_type"),
        ({"title": "x", "current_level": "expert"}, "body.current_level"),
        ({"title": "x", "daily_minutes": 9}, "body.daily_minutes"),
        ({"title": "x", "daily_minutes": 481}, "body.daily_minutes"),
        ({"title": "x", "daily_minutes": "lots"}, "body.daily_minutes"),
        ({"title": "x", "preferred_languages": []}, "body.preferred_languages"),
        ({"title": "x", "preferred_languages": ["fr"]}, "body.preferred_languages"),
        ({"title": "x", "preferred_languages": ["en"] * 6}, "body.preferred_languages"),
        ({"title": "x", "target_date": "2001-01-01"}, "body.target_date"),
        ({"title": "x", "target_date": "not-a-date"}, "body.target_date"),
        ({"title": "x", "target_date": "2999-01-01"}, "body.target_date"),
        ({"title": "x", "status": "archived"}, "body.status"),
        ({"title": "x", "id": str(uuid.uuid4())}, "body.id"),
    ],
)
def test_invalid_goals_are_rejected_with_field_level_errors(
    api: TestClient, make_learner: MakeLearner, payload: dict[str, Any], field: str
) -> None:
    response = api.post("/v1/goals", headers=make_learner().headers, json=payload)

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert field in error_fields(response)


def test_validation_errors_never_echo_what_was_submitted(
    api: TestClient, make_learner: MakeLearner
) -> None:
    response = api.post(
        "/v1/goals",
        headers=make_learner().headers,
        json={"title": "x", "daily_minutes": "S3CRET-NOT-A-NUMBER"},
    )

    assert response.status_code == 422
    assert "S3CRET" not in response.text


def test_malformed_json_is_a_client_error_not_a_server_error(
    api: TestClient, make_learner: MakeLearner
) -> None:
    response = api.post(
        "/v1/goals",
        headers={**make_learner().headers, "Content-Type": "application/json"},
        content="{not json",
    )

    assert response.status_code == 422


def test_an_invalid_goal_id_in_the_path_is_a_client_error(
    api: TestClient, make_learner: MakeLearner
) -> None:
    response = api.get("/v1/goals/not-a-uuid", headers=make_learner().headers)

    assert response.status_code == 422
    assert "path.goal_id" in error_fields(response)


def test_today_is_an_acceptable_target_date(api: TestClient, make_learner: MakeLearner) -> None:
    goal = create(api, make_learner(), target_date=today_utc().isoformat())

    assert goal["target_date"] == today_utc().isoformat()


# --- Pagination and filtering ----------------------------------------------------------------


def test_goals_are_listed_newest_first_across_cursor_pages(
    api: TestClient, make_learner: MakeLearner
) -> None:
    learner = make_learner()
    created = [create(api, learner, title=f"Goal {n}")["id"] for n in range(5)]

    seen: list[str] = []
    cursor: str | None = None
    pages = 0
    while True:
        params: dict[str, Any] = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        page = api.get("/v1/goals", headers=learner.headers, params=params).json()
        seen += [item["id"] for item in page["items"]]
        pages += 1
        cursor = page["next_cursor"]
        if cursor is None:
            break

    assert seen == list(reversed(created))  # newest first, no duplicates, none missing
    assert pages == 3


def test_a_page_that_exactly_fills_the_limit_has_no_next_cursor(
    api: TestClient, make_learner: MakeLearner
) -> None:
    learner = make_learner()
    create(api, learner)
    create(api, learner)

    page = api.get("/v1/goals", headers=learner.headers, params={"limit": 2}).json()

    assert len(page["items"]) == 2
    assert page["next_cursor"] is None


@pytest.mark.parametrize("cursor", ["!!!", "bm90LWpzb24", "e30", "a" * 150])
def test_an_invalid_cursor_is_rejected(
    api: TestClient, make_learner: MakeLearner, cursor: str
) -> None:
    response = api.get("/v1/goals", headers=make_learner().headers, params={"cursor": cursor})

    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_CURSOR"


@pytest.mark.parametrize("limit", [0, -1, 51, "many"])
def test_the_page_size_is_bounded(api: TestClient, make_learner: MakeLearner, limit: Any) -> None:
    response = api.get("/v1/goals", headers=make_learner().headers, params={"limit": limit})

    assert response.status_code == 422


def test_archived_goals_are_hidden_unless_asked_for(
    api: TestClient, make_learner: MakeLearner, database_dsn: str
) -> None:
    learner = make_learner()
    kept, shelved = create(api, learner, title="Kept"), create(api, learner, title="Shelved")
    archive(database_dsn, shelved["id"])

    default = api.get("/v1/goals", headers=learner.headers).json()["items"]
    archived = api.get("/v1/goals", headers=learner.headers, params={"status": "archived"}).json()[
        "items"
    ]
    active = api.get("/v1/goals", headers=learner.headers, params={"status": "active"}).json()[
        "items"
    ]

    assert [g["id"] for g in default] == [kept["id"]]
    assert [g["id"] for g in archived] == [shelved["id"]]
    assert [g["id"] for g in active] == [kept["id"]]


def test_an_unknown_status_filter_is_rejected(api: TestClient, make_learner: MakeLearner) -> None:
    response = api.get("/v1/goals", headers=make_learner().headers, params={"status": "bogus"})

    assert response.status_code == 422


# --- Limits ----------------------------------------------------------------------------------


def test_the_goal_limit_is_enforced_and_archiving_frees_a_slot(
    api: TestClient,
    api_settings: Any,
    monkeypatch: pytest.MonkeyPatch,
    make_learner: MakeLearner,
    database_dsn: str,
) -> None:
    monkeypatch.setattr(api_settings, "max_active_goals_per_user", 2)
    learner = make_learner()

    first = create(api, learner, title="One")
    create(api, learner, title="Two")
    refused = api.post("/v1/goals", headers=learner.headers, json={"title": "Three"})
    archive(database_dsn, first["id"])
    accepted = api.post("/v1/goals", headers=learner.headers, json={"title": "Three"})

    assert refused.status_code == 409
    assert refused.json()["code"] == "GOAL_LIMIT_REACHED"
    assert accepted.status_code == 201


def test_one_users_limit_does_not_affect_another_user(
    api: TestClient,
    api_settings: Any,
    monkeypatch: pytest.MonkeyPatch,
    make_learner: MakeLearner,
) -> None:
    monkeypatch.setattr(api_settings, "max_active_goals_per_user", 1)
    alice, bob = make_learner(), make_learner()

    create(api, alice)
    bobs = api.post("/v1/goals", headers=bob.headers, json={"title": "Bob's first"})

    assert bobs.status_code == 201
