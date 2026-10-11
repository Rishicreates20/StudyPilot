"""Managing goals over HTTP: edit, pause, complete, archive, restore, delete, summary, filters.

Every operation is also tried as a different user and without credentials, because ownership and
authentication are the properties that must never regress.
"""

import uuid
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
import structlog
from fastapi.testclient import TestClient

from app.schemas.goals import today_utc
from conftest import Learner
from support.api_helpers import create_goal, errors_by_field, goal_in_status, set_status
from support.database import admin

MakeLearner = Callable[..., Learner]

STATUSES = ("active", "paused", "completed", "archived")
LEGAL = {
    ("active", "paused"),
    ("active", "completed"),
    ("active", "archived"),
    ("paused", "active"),
    ("paused", "completed"),
    ("paused", "archived"),
    ("completed", "active"),
    ("completed", "archived"),
    ("archived", "active"),
}


def patch(api: TestClient, learner: Learner, goal_id: str, **fields: Any) -> Any:
    return api.patch(f"/v1/goals/{goal_id}", headers=learner.headers, json=fields)


def read(api: TestClient, learner: Learner, goal_id: str) -> dict[str, Any]:
    response = api.get(f"/v1/goals/{goal_id}", headers=learner.headers)
    assert response.status_code == 200, response.text
    return response.json()


# --- Editing -----------------------------------------------------------------------------------


def test_editing_changes_only_the_fields_sent(api: TestClient, make_learner: MakeLearner) -> None:
    learner = make_learner()
    goal = create_goal(
        api, learner, title="Learn Docker", description="Containers", goal_type="certification"
    )

    response = patch(api, learner, goal["id"], title="  Learn Kubernetes  ", daily_minutes=45)

    assert response.status_code == 200
    edited = response.json()
    assert edited["title"] == "Learn Kubernetes"  # trimmed
    assert edited["daily_minutes"] == 45
    assert edited["description"] == "Containers"  # untouched
    assert edited["goal_type"] == "certification"
    assert edited["id"] == goal["id"] and edited["created_at"] == goal["created_at"]
    assert edited["updated_at"] > goal["updated_at"]


def test_every_editable_field_can_be_changed_and_persists(
    api: TestClient, make_learner: MakeLearner
) -> None:
    learner = make_learner()
    goal = create_goal(api, learner)
    target = (today_utc() + timedelta(days=90)).isoformat()

    response = patch(
        api,
        learner,
        goal["id"],
        title="Pass the CKA exam",
        description="Exam on the 1st",
        goal_type="exam",
        current_level="intermediate",
        target_date=target,
        daily_minutes=120,
        preferred_languages=["hi", "en"],
        learning_preferences=["quizzes"],
    )

    assert response.status_code == 200
    fresh = read(api, learner, goal["id"])  # a separate request: it is really stored
    assert fresh == response.json()
    assert fresh["goal_type"] == "exam"
    assert fresh["current_level"] == "intermediate"
    assert fresh["target_date"] == target
    assert fresh["preferred_languages"] == ["hi", "en"]
    assert fresh["learning_preferences"] == ["quizzes"]


def test_null_clears_the_optional_fields(api: TestClient, make_learner: MakeLearner) -> None:
    learner = make_learner()
    target = (today_utc() + timedelta(days=30)).isoformat()
    goal = create_goal(api, learner, description="Notes", target_date=target)

    response = patch(api, learner, goal["id"], description=None, target_date=None)

    assert response.status_code == 200
    assert response.json()["description"] is None
    assert response.json()["target_date"] is None


def test_a_blank_description_clears_it(api: TestClient, make_learner: MakeLearner) -> None:
    learner = make_learner()
    goal = create_goal(api, learner, description="Notes")

    assert patch(api, learner, goal["id"], description="   ").json()["description"] is None


def test_saving_an_unchanged_goal_does_not_touch_it(
    api: TestClient, make_learner: MakeLearner
) -> None:
    learner = make_learner()
    goal = create_goal(api, learner, title="Same", daily_minutes=30)

    response = patch(api, learner, goal["id"], title="Same", daily_minutes=30)

    assert response.status_code == 200
    assert response.json()["updated_at"] == goal["updated_at"]


@pytest.mark.parametrize(
    ("fields", "expected_field"),
    [
        ({"title": ""}, "title"),
        ({"title": "   "}, "title"),
        ({"title": "t" * 201}, "title"),
        ({"description": "d" * 2001}, "description"),
        ({"goal_type": "hobby"}, "goal_type"),
        ({"current_level": "expert"}, "current_level"),
        ({"daily_minutes": 9}, "daily_minutes"),
        ({"daily_minutes": 481}, "daily_minutes"),
        ({"daily_minutes": "lots"}, "daily_minutes"),
        ({"preferred_languages": []}, "preferred_languages"),
        ({"preferred_languages": ["xx"]}, "preferred_languages"),
        ({"learning_preferences": ["flashcards"]}, "learning_preferences"),
        ({"learning_preferences": ["a", "b", "c", "d"]}, "learning_preferences"),
        ({"target_date": "next week"}, "target_date"),
    ],
)
def test_invalid_edits_are_rejected_with_the_field_named(
    api: TestClient, make_learner: MakeLearner, fields: dict[str, Any], expected_field: str
) -> None:
    learner = make_learner()
    goal = create_goal(api, learner)

    response = patch(api, learner, goal["id"], **fields)

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert expected_field in errors_by_field(response.json())
    assert read(api, learner, goal["id"]) == goal  # nothing was changed


@pytest.mark.parametrize(
    "field", ["title", "goal_type", "current_level", "daily_minutes", "preferred_languages"]
)
def test_required_fields_cannot_be_cleared_with_null(
    api: TestClient, make_learner: MakeLearner, field: str
) -> None:
    learner = make_learner()
    goal = create_goal(api, learner)

    response = patch(api, learner, goal["id"], **{field: None})

    assert response.status_code == 422
    assert field in errors_by_field(response.json())


def test_an_empty_edit_is_rejected(api: TestClient, make_learner: MakeLearner) -> None:
    learner = make_learner()
    goal = create_goal(api, learner)

    assert patch(api, learner, goal["id"]).status_code == 422


@pytest.mark.parametrize(
    "field",
    ["id", "user_id", "status", "created_at", "updated_at", "completed_at", "archived_at"],
)
def test_an_edit_cannot_set_fields_the_server_owns(
    api: TestClient, make_learner: MakeLearner, field: str
) -> None:
    learner = make_learner()
    other = make_learner()
    goal = create_goal(api, learner)
    value = str(other.id) if field in {"id", "user_id"} else "archived"

    response = patch(api, learner, goal["id"], **{field: value})

    assert response.status_code == 422
    assert read(api, learner, goal["id"]) == goal


def test_a_changed_target_date_may_not_be_in_the_past(
    api: TestClient, make_learner: MakeLearner
) -> None:
    learner = make_learner()
    goal = create_goal(api, learner)
    yesterday_but_one = (today_utc() - timedelta(days=3)).isoformat()

    response = patch(api, learner, goal["id"], target_date=yesterday_but_one)

    assert response.status_code == 422
    assert "target_date" in errors_by_field(response.json())


def test_a_goal_whose_date_has_passed_can_still_be_renamed(
    api: TestClient, make_learner: MakeLearner, database_dsn: str
) -> None:
    learner = make_learner()
    goal = create_goal(api, learner)
    past = (today_utc() - timedelta(days=30)).isoformat()
    admin(database_dsn).execute(
        "update public.learning_goals set target_date = %s where id = %s", (past, goal["id"])
    )

    # The edit form sends every field back, including the unchanged (now past) date.
    response = patch(api, learner, goal["id"], title="Renamed", target_date=past)

    assert response.status_code == 200
    assert response.json()["title"] == "Renamed"
    assert response.json()["target_date"] == past


def test_an_archived_goal_cannot_be_edited_until_restored(
    api: TestClient, make_learner: MakeLearner
) -> None:
    learner = make_learner()
    goal = goal_in_status(api, learner, "archived")

    refused = patch(api, learner, goal["id"], title="Renamed")
    set_status(api, learner, goal["id"], "active")
    accepted = patch(api, learner, goal["id"], title="Renamed")

    assert refused.status_code == 409
    assert refused.json()["code"] == "GOAL_ARCHIVED"
    assert accepted.status_code == 200


@pytest.mark.parametrize("status", ["paused", "completed"])
def test_paused_and_completed_goals_can_be_edited(
    api: TestClient, make_learner: MakeLearner, status: str
) -> None:
    learner = make_learner()
    goal = goal_in_status(api, learner, status)

    response = patch(api, learner, goal["id"], description="Updated notes")

    assert response.status_code == 200
    assert response.json()["status"] == status  # editing never changes the status


# --- Status lifecycle --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("current", "target"),
    [(a, b) for a in STATUSES for b in STATUSES if a != b],
)
def test_status_changes_follow_the_lifecycle(
    api: TestClient, make_learner: MakeLearner, current: str, target: str
) -> None:
    learner = make_learner()
    goal = goal_in_status(api, learner, current)

    response = api.put(
        f"/v1/goals/{goal['id']}/status", headers=learner.headers, json={"status": target}
    )

    if (current, target) in LEGAL:
        assert response.status_code == 200, response.text
        changed = response.json()
        assert changed["status"] == target
        assert (changed["completed_at"] is not None) == (target == "completed")
        assert (changed["archived_at"] is not None) == (target == "archived")
        assert read(api, learner, goal["id"])["status"] == target
    else:
        assert response.status_code == 409
        assert response.json()["code"] == "INVALID_STATUS_TRANSITION"
        assert response.json()["detail"]
        assert read(api, learner, goal["id"])["status"] == current


@pytest.mark.parametrize("status", STATUSES)
def test_asking_for_the_current_status_changes_nothing(
    api: TestClient, make_learner: MakeLearner, status: str
) -> None:
    learner = make_learner()
    goal = goal_in_status(api, learner, status)

    again = set_status(api, learner, goal["id"], status)

    assert again == goal


def test_a_full_lifecycle_round_trip(api: TestClient, make_learner: MakeLearner) -> None:
    learner = make_learner()
    goal = create_goal(api, learner)

    for status in ("paused", "active", "completed", "active", "archived", "active"):
        assert set_status(api, learner, goal["id"], status)["status"] == status

    final = read(api, learner, goal["id"])
    assert final["completed_at"] is None and final["archived_at"] is None


@pytest.mark.parametrize("body", [{"status": "deleted"}, {"status": None}, {}, {"state": "paused"}])
def test_an_invalid_status_request_is_rejected(
    api: TestClient, make_learner: MakeLearner, body: dict[str, Any]
) -> None:
    learner = make_learner()
    goal = create_goal(api, learner)

    response = api.put(f"/v1/goals/{goal['id']}/status", headers=learner.headers, json=body)

    assert response.status_code == 422


def test_the_status_request_cannot_carry_other_changes(
    api: TestClient, make_learner: MakeLearner
) -> None:
    learner = make_learner()
    goal = create_goal(api, learner, title="Original")

    response = api.put(
        f"/v1/goals/{goal['id']}/status",
        headers=learner.headers,
        json={"status": "paused", "title": "Sneaky rename"},
    )

    assert response.status_code == 422
    assert read(api, learner, goal["id"])["title"] == "Original"


def test_restoring_a_goal_respects_the_goal_limit(
    api: TestClient,
    api_settings: Any,
    monkeypatch: pytest.MonkeyPatch,
    make_learner: MakeLearner,
) -> None:
    monkeypatch.setattr(api_settings, "max_active_goals_per_user", 2)
    learner = make_learner()
    first = create_goal(api, learner, title="One")
    set_status(api, learner, first["id"], "archived")
    create_goal(api, learner, title="Two")
    create_goal(api, learner, title="Three")  # the limit is now full

    response = api.put(
        f"/v1/goals/{first['id']}/status", headers=learner.headers, json={"status": "active"}
    )

    assert response.status_code == 409
    assert response.json()["code"] == "GOAL_LIMIT_REACHED"
    assert read(api, learner, first["id"])["status"] == "archived"


# --- Deleting ----------------------------------------------------------------------------------


def test_an_archived_goal_can_be_deleted_for_good(
    api: TestClient, make_learner: MakeLearner, database_dsn: str
) -> None:
    learner = make_learner()
    goal = goal_in_status(api, learner, "archived")

    deleted = api.delete(f"/v1/goals/{goal['id']}", headers=learner.headers)

    assert deleted.status_code == 204
    assert deleted.content == b""
    assert api.get(f"/v1/goals/{goal['id']}", headers=learner.headers).status_code == 404
    gone = admin(database_dsn).fetchone(
        "select 1 as present from public.learning_goals where id = %s", (goal["id"],)
    )
    assert gone is None


@pytest.mark.parametrize("status", ["active", "paused", "completed"])
def test_a_goal_must_be_archived_before_it_can_be_deleted(
    api: TestClient, make_learner: MakeLearner, status: str
) -> None:
    learner = make_learner()
    goal = goal_in_status(api, learner, status)

    response = api.delete(f"/v1/goals/{goal['id']}", headers=learner.headers)

    assert response.status_code == 409
    assert response.json()["code"] == "GOAL_NOT_ARCHIVED"
    assert read(api, learner, goal["id"])["status"] == status


def test_deleting_twice_is_not_found_the_second_time(
    api: TestClient, make_learner: MakeLearner
) -> None:
    learner = make_learner()
    goal = goal_in_status(api, learner, "archived")

    first = api.delete(f"/v1/goals/{goal['id']}", headers=learner.headers)
    second = api.delete(f"/v1/goals/{goal['id']}", headers=learner.headers)

    assert (first.status_code, second.status_code) == (204, 404)


def test_deleting_a_goal_frees_its_place_in_the_counts(
    api: TestClient, make_learner: MakeLearner
) -> None:
    learner = make_learner()
    goal = goal_in_status(api, learner, "archived")

    api.delete(f"/v1/goals/{goal['id']}", headers=learner.headers)

    assert api.get("/v1/goals/summary", headers=learner.headers).json()["archived"] == 0


# --- Other users cannot touch a goal -----------------------------------------------------------

WRITES = [
    ("PATCH", "", {"title": "Hijacked"}),
    ("PUT", "/status", {"status": "archived"}),
    ("DELETE", "", None),
]


@pytest.mark.parametrize(("method", "suffix", "body"), WRITES)
def test_another_user_cannot_change_or_delete_a_goal(
    api: TestClient,
    make_learner: MakeLearner,
    method: str,
    suffix: str,
    body: dict[str, Any] | None,
) -> None:
    alice, mallory = make_learner(), make_learner()
    goal = goal_in_status(api, alice, "archived")  # archived, so a delete would be legal for Alice

    response = api.request(
        method, f"/v1/goals/{goal['id']}{suffix}", headers=mallory.headers, json=body
    )

    assert response.status_code == 404
    assert response.json()["code"] == "GOAL_NOT_FOUND"
    assert read(api, alice, goal["id"]) == goal  # untouched


@pytest.mark.parametrize(("method", "suffix", "body"), [("GET", "", None), *WRITES])
def test_a_foreign_goal_looks_exactly_like_a_missing_one(
    api: TestClient,
    make_learner: MakeLearner,
    method: str,
    suffix: str,
    body: dict[str, Any] | None,
) -> None:
    alice, mallory = make_learner(), make_learner()
    goal = create_goal(api, alice)

    foreign = api.request(
        method, f"/v1/goals/{goal['id']}{suffix}", headers=mallory.headers, json=body
    )
    missing = api.request(
        method, f"/v1/goals/{uuid.uuid4()}{suffix}", headers=mallory.headers, json=body
    )

    assert foreign.status_code == missing.status_code == 404
    assert foreign.json()["code"] == missing.json()["code"]
    assert foreign.json()["detail"] == missing.json()["detail"]


def test_a_malformed_goal_id_is_a_client_error_for_every_method(
    api: TestClient, make_learner: MakeLearner
) -> None:
    learner = make_learner()
    for method, suffix, body in [("GET", "", None), *WRITES]:
        response = api.request(
            method, f"/v1/goals/not-a-uuid{suffix}", headers=learner.headers, json=body
        )
        assert response.status_code == 422, f"{method} answered {response.status_code}"


@pytest.mark.parametrize(("method", "suffix", "body"), [("GET", "", None), *WRITES])
def test_every_goal_operation_requires_authentication(
    api: TestClient, method: str, suffix: str, body: dict[str, Any] | None
) -> None:
    response = api.request(method, f"/v1/goals/{uuid.uuid4()}{suffix}", json=body)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_an_invalid_token_cannot_manage_goals(api: TestClient, make_learner: MakeLearner) -> None:
    goal = create_goal(api, make_learner())

    response = api.patch(
        f"/v1/goals/{goal['id']}",
        headers={"Authorization": "Bearer not.a.token"},
        json={"title": "Hijacked"},
    )

    assert response.status_code == 401


# --- Listing and counting ----------------------------------------------------------------------


def test_the_default_list_hides_archived_goals_and_the_filter_finds_them(
    api: TestClient, make_learner: MakeLearner
) -> None:
    learner = make_learner()
    active = create_goal(api, learner, title="Active")
    paused = goal_in_status(api, learner, "paused", title="Paused")
    done = goal_in_status(api, learner, "completed", title="Done")
    archived = goal_in_status(api, learner, "archived", title="Archived")

    def titles(**params: Any) -> set[str]:
        response = api.get("/v1/goals", headers=learner.headers, params=params)
        assert response.status_code == 200, response.text
        return {goal["title"] for goal in response.json()["items"]}

    assert titles() == {active["title"], paused["title"], done["title"]}
    assert titles(status="archived") == {archived["title"]}
    assert titles(status="completed") == {done["title"]}
    assert titles(status=["active", "paused"]) == {active["title"], paused["title"]}
    assert titles(status=["completed", "archived"]) == {done["title"], archived["title"]}


def test_filters_work_with_pagination(api: TestClient, make_learner: MakeLearner) -> None:
    learner = make_learner()
    done = [goal_in_status(api, learner, "completed", title=f"Done {n}") for n in range(3)]
    create_goal(api, learner, title="Still active")

    first = api.get(
        "/v1/goals", headers=learner.headers, params={"status": "completed", "limit": 2}
    ).json()
    second = api.get(
        "/v1/goals",
        headers=learner.headers,
        params={"status": "completed", "limit": 2, "cursor": first["next_cursor"]},
    ).json()

    seen = [goal["id"] for goal in first["items"] + second["items"]]
    assert sorted(seen) == sorted(goal["id"] for goal in done)
    assert second["next_cursor"] is None


def test_listing_by_status_never_includes_other_users(
    api: TestClient, make_learner: MakeLearner
) -> None:
    alice, bob = make_learner(), make_learner()
    goal_in_status(api, alice, "completed", title="Alice done")

    response = api.get("/v1/goals", headers=bob.headers, params={"status": "completed"})

    assert response.json()["items"] == []


def test_the_summary_counts_each_state_for_the_caller_only(
    api: TestClient, make_learner: MakeLearner
) -> None:
    alice, bob = make_learner(), make_learner()
    create_goal(api, alice)
    create_goal(api, alice)
    goal_in_status(api, alice, "paused")
    goal_in_status(api, alice, "completed")
    goal_in_status(api, alice, "archived")
    goal_in_status(api, bob, "completed")

    alices = api.get("/v1/goals/summary", headers=alice.headers)
    brand_new = api.get("/v1/goals/summary", headers=make_learner().headers)

    assert alices.status_code == 200
    assert alices.json() == {"active": 2, "paused": 1, "completed": 1, "archived": 1}
    assert brand_new.json() == {"active": 0, "paused": 0, "completed": 0, "archived": 0}


def test_the_summary_route_is_not_mistaken_for_a_goal_id(
    api: TestClient, make_learner: MakeLearner
) -> None:
    response = api.get("/v1/goals/summary", headers=make_learner().headers)

    assert response.status_code == 200  # not a 422 about "summary" not being a UUID


# --- Logging -----------------------------------------------------------------------------------


def test_management_logs_name_fields_and_ids_but_never_goal_content(
    api: TestClient, make_learner: MakeLearner
) -> None:
    learner = make_learner()
    goal = create_goal(api, learner, title="A very private goal title")

    with structlog.testing.capture_logs() as logs:
        patch(api, learner, goal["id"], title="A new private title", description="Private notes")
        set_status(api, learner, goal["id"], "archived")

    text = repr(logs)
    assert "goal.updated" in text and "goal.status_changed" in text
    assert "A new private title" not in text and "Private notes" not in text
    assert "A very private goal title" not in text
    assert learner.token not in text and learner.email not in text
