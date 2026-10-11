"""Profile, saved preferences and onboarding over HTTP."""

import uuid
from collections.abc import Callable
from typing import Any

import pytest
import structlog
from fastapi.testclient import TestClient

from conftest import Learner
from support.api_helpers import create_goal, errors_by_field
from support.database import admin

MakeLearner = Callable[..., Learner]


def patch_me(api: TestClient, learner: Learner, **fields: Any) -> Any:
    return api.patch("/v1/me", headers=learner.headers, json=fields)


def read_me(api: TestClient, learner: Learner) -> dict[str, Any]:
    response = api.get("/v1/me", headers=learner.headers)
    assert response.status_code == 200, response.text
    return response.json()


# --- Reading and updating ----------------------------------------------------------------------


def test_a_new_account_has_default_preferences_and_has_not_been_onboarded(
    api: TestClient, make_learner: MakeLearner
) -> None:
    me = read_me(api, make_learner())

    assert me["onboarding_completed"] is False
    assert me["preferences"] == {
        "default_daily_minutes": 60,
        "preferred_languages": ["en"],
        "learning_preferences": ["examples", "quizzes", "revision"],
    }


def test_preferences_and_profile_changes_persist(
    api: TestClient, make_learner: MakeLearner
) -> None:
    learner = make_learner()

    response = patch_me(
        api,
        learner,
        display_name="  Ada Lovelace ",
        locale="hi",
        timezone="Asia/Kolkata",
        default_daily_minutes=90,
        preferred_languages=["hi", "en"],
        learning_preferences=["quizzes", "revision"],
    )

    assert response.status_code == 200
    me = read_me(api, learner)  # a separate request: it is really stored
    assert me == response.json()
    assert me["display_name"] == "Ada Lovelace"
    assert me["locale"] == "hi"
    assert me["preferences"] == {
        "default_daily_minutes": 90,
        "preferred_languages": ["hi", "en"],
        "learning_preferences": ["quizzes", "revision"],
    }


def test_only_the_fields_sent_change(api: TestClient, make_learner: MakeLearner) -> None:
    learner = make_learner(display_name="Ada")

    patch_me(api, learner, default_daily_minutes=30)

    me = read_me(api, learner)
    assert me["display_name"] == "Ada"
    assert me["preferences"]["default_daily_minutes"] == 30
    assert me["preferences"]["preferred_languages"] == ["en"]


def test_the_name_can_be_cleared(api: TestClient, make_learner: MakeLearner) -> None:
    learner = make_learner(display_name="Ada")

    assert patch_me(api, learner, display_name=None).json()["display_name"] is None
    assert patch_me(api, learner, display_name="Ada").json()["display_name"] == "Ada"
    assert patch_me(api, learner, display_name="   ").json()["display_name"] is None


def test_no_learning_preferences_is_a_valid_choice(
    api: TestClient, make_learner: MakeLearner
) -> None:
    learner = make_learner()

    response = patch_me(api, learner, learning_preferences=[])

    assert response.status_code == 200
    assert response.json()["preferences"]["learning_preferences"] == []


def test_duplicate_choices_are_collapsed(api: TestClient, make_learner: MakeLearner) -> None:
    response = patch_me(
        api,
        make_learner(),
        preferred_languages=["en", "en", "hi"],
        learning_preferences=["quizzes", "quizzes"],
    )

    assert response.json()["preferences"]["preferred_languages"] == ["en", "hi"]
    assert response.json()["preferences"]["learning_preferences"] == ["quizzes"]


@pytest.mark.parametrize(
    ("fields", "expected_field"),
    [
        ({"display_name": "n" * 81}, "display_name"),
        ({"locale": "fr"}, "locale"),
        ({"timezone": "Mars/Olympus_Mons"}, "timezone"),
        ({"timezone": "../../etc/passwd"}, "timezone"),
        ({"timezone": ""}, "timezone"),
        ({"default_daily_minutes": 9}, "default_daily_minutes"),
        ({"default_daily_minutes": 481}, "default_daily_minutes"),
        ({"preferred_languages": []}, "preferred_languages"),
        ({"preferred_languages": ["xx"]}, "preferred_languages"),
        ({"learning_preferences": ["flashcards"]}, "learning_preferences"),
    ],
)
def test_invalid_values_are_rejected_with_the_field_named(
    api: TestClient, make_learner: MakeLearner, fields: dict[str, Any], expected_field: str
) -> None:
    learner = make_learner()
    before = read_me(api, learner)

    response = patch_me(api, learner, **fields)

    assert response.status_code == 422
    assert expected_field in errors_by_field(response.json())
    assert read_me(api, learner) == before


@pytest.mark.parametrize(
    "field", ["locale", "timezone", "default_daily_minutes", "preferred_languages"]
)
def test_required_settings_cannot_be_cleared_with_null(
    api: TestClient, make_learner: MakeLearner, field: str
) -> None:
    response = patch_me(api, make_learner(), **{field: None})

    assert response.status_code == 422
    assert field in errors_by_field(response.json())


def test_an_empty_update_is_rejected(api: TestClient, make_learner: MakeLearner) -> None:
    assert patch_me(api, make_learner()).status_code == 422


@pytest.mark.parametrize(
    "field", ["id", "email", "created_at", "onboarding_completed", "onboarding_completed_at"]
)
def test_the_update_cannot_set_fields_the_server_owns(
    api: TestClient, make_learner: MakeLearner, field: str
) -> None:
    learner = make_learner()
    before = read_me(api, learner)

    response = patch_me(api, learner, **{field: str(uuid.uuid4())})

    assert response.status_code == 422
    assert read_me(api, learner) == before


# --- Whose preferences are these ---------------------------------------------------------------


def test_one_users_preferences_never_reach_another(
    api: TestClient, make_learner: MakeLearner
) -> None:
    alice, bob = make_learner(), make_learner()

    patch_me(api, alice, default_daily_minutes=240, display_name="Alice")

    bobs = read_me(api, bob)
    assert bobs["preferences"]["default_daily_minutes"] == 60
    assert bobs["display_name"] is None


def test_the_update_applies_to_the_token_holder_whatever_the_body_says(
    api: TestClient, make_learner: MakeLearner
) -> None:
    alice, bob = make_learner(), make_learner()

    response = api.patch(
        "/v1/me", headers=bob.headers, json={"id": str(alice.id), "default_daily_minutes": 15}
    )

    assert response.status_code == 422  # naming another user is refused outright
    assert read_me(api, alice)["preferences"]["default_daily_minutes"] == 60
    assert read_me(api, bob)["preferences"]["default_daily_minutes"] == 60


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("PATCH", "/v1/me", {"default_daily_minutes": 30}),
        ("POST", "/v1/me/onboarding/complete", None),
    ],
)
def test_changing_a_profile_requires_authentication(
    api: TestClient, method: str, path: str, body: dict[str, Any] | None
) -> None:
    response = api.request(method, path, json=body)

    assert response.status_code == 401


def test_a_deleted_account_cannot_change_its_profile(
    api: TestClient, make_learner: MakeLearner, database_dsn: str
) -> None:
    learner = make_learner()
    admin(database_dsn).execute("delete from auth.users where id = %s", (learner.id,))

    response = patch_me(api, learner, default_daily_minutes=30)

    assert response.status_code == 401
    assert response.json()["code"] == "ACCOUNT_NOT_FOUND"


# --- Onboarding --------------------------------------------------------------------------------


def test_completing_onboarding_is_remembered(api: TestClient, make_learner: MakeLearner) -> None:
    learner = make_learner()

    response = api.post("/v1/me/onboarding/complete", headers=learner.headers)

    assert response.status_code == 200
    assert response.json()["onboarding_completed"] is True
    assert read_me(api, learner)["onboarding_completed"] is True


def test_completing_onboarding_twice_keeps_the_first_time(
    api: TestClient, make_learner: MakeLearner, database_dsn: str
) -> None:
    learner = make_learner()
    api.post("/v1/me/onboarding/complete", headers=learner.headers)
    first = admin(database_dsn).scalar(
        "select onboarding_completed_at from public.profiles where id = %s", (learner.id,)
    )

    again = api.post("/v1/me/onboarding/complete", headers=learner.headers)

    assert again.status_code == 200
    second = admin(database_dsn).scalar(
        "select onboarding_completed_at from public.profiles where id = %s", (learner.id,)
    )
    assert first == second


def test_one_users_onboarding_does_not_complete_anothers(
    api: TestClient, make_learner: MakeLearner
) -> None:
    alice, bob = make_learner(), make_learner()

    api.post("/v1/me/onboarding/complete", headers=alice.headers)

    assert read_me(api, bob)["onboarding_completed"] is False


# --- Preferences shape new goals ---------------------------------------------------------------


def test_new_goals_start_from_the_saved_preferences(
    api: TestClient, make_learner: MakeLearner
) -> None:
    learner = make_learner()
    patch_me(
        api,
        learner,
        default_daily_minutes=90,
        preferred_languages=["hi"],
        learning_preferences=["quizzes"],
    )

    goal = create_goal(api, learner)

    assert goal["daily_minutes"] == 90
    assert goal["preferred_languages"] == ["hi"]
    assert goal["learning_preferences"] == ["quizzes"]


def test_a_goal_can_override_every_saved_preference(
    api: TestClient, make_learner: MakeLearner
) -> None:
    learner = make_learner()
    patch_me(api, learner, default_daily_minutes=90, preferred_languages=["hi"])

    goal = create_goal(
        api,
        learner,
        daily_minutes=20,
        preferred_languages=["or"],
        learning_preferences=[],
    )

    assert goal["daily_minutes"] == 20
    assert goal["preferred_languages"] == ["or"]
    assert goal["learning_preferences"] == []  # an explicit empty choice is respected


def test_changing_preferences_does_not_rewrite_existing_goals(
    api: TestClient, make_learner: MakeLearner
) -> None:
    learner = make_learner()
    goal = create_goal(api, learner)

    patch_me(api, learner, default_daily_minutes=300, learning_preferences=[])

    fresh = api.get(f"/v1/goals/{goal['id']}", headers=learner.headers).json()
    assert fresh["daily_minutes"] == 60
    assert fresh["learning_preferences"] == ["examples", "quizzes", "revision"]


# --- Logging -----------------------------------------------------------------------------------


def test_profile_logs_name_fields_but_never_personal_data(
    api: TestClient, make_learner: MakeLearner
) -> None:
    learner = make_learner()

    with structlog.testing.capture_logs() as logs:
        patch_me(api, learner, display_name="Ada Lovelace", default_daily_minutes=75)
        api.post("/v1/me/onboarding/complete", headers=learner.headers)

    text = repr(logs)
    assert "profile.updated" in text and "onboarding.completed" in text
    assert "Ada Lovelace" not in text
    assert learner.token not in text and learner.email not in text
