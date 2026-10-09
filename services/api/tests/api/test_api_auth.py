"""Authentication at the HTTP boundary: valid, invalid, expired and missing credentials."""

import uuid
from collections.abc import Callable

import pytest
import structlog
from fastapi.testclient import TestClient

from conftest import Learner
from support.database import admin
from support.keys import (
    SigningKey,
    build_claims,
    make_ec_key,
    sign_hs256,
    sign_with_key,
)

PROBLEM_JSON = "application/problem+json"
MakeLearner = Callable[..., Learner]


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --- Accepted ----------------------------------------------------------------------------------


def test_a_valid_token_returns_the_callers_own_profile(
    api: TestClient, make_learner: MakeLearner
) -> None:
    learner = make_learner(display_name="Ada")

    response = api.get("/v1/me", headers=learner.headers)

    assert response.status_code == 200
    assert response.json() | {"created_at": None} == {
        "id": str(learner.id),
        "email": learner.email,  # from the verified token, not from the request
        "display_name": "Ada",
        "locale": "en",
        "timezone": "Asia/Kolkata",
        "created_at": None,
    }


def test_the_identity_comes_from_the_token_whatever_the_client_claims(
    api: TestClient, make_learner: MakeLearner
) -> None:
    alice, bob = make_learner(display_name="Alice"), make_learner(display_name="Bob")

    response = api.get(
        "/v1/me",
        headers={
            **alice.headers,
            # None of these may influence who the caller is.
            "X-User-Id": str(bob.id),
            "X-Forwarded-User": str(bob.id),
        },
        params={"user_id": str(bob.id)},
    )

    assert response.status_code == 200
    assert response.json()["id"] == str(alice.id)
    assert response.json()["display_name"] == "Alice"


def test_the_token_scheme_is_case_insensitive(api: TestClient, make_learner: MakeLearner) -> None:
    learner = make_learner()

    response = api.get("/v1/me", headers={"Authorization": f"bearer {learner.token}"})

    assert response.status_code == 200


# --- Missing and malformed credentials --------------------------------------------------------


def test_a_request_without_credentials_is_unauthenticated(api: TestClient) -> None:
    response = api.get("/v1/me")
    body = response.json()

    assert response.status_code == 401
    assert response.headers["content-type"].startswith(PROBLEM_JSON)
    assert response.headers["www-authenticate"] == "Bearer"
    assert body["code"] == "UNAUTHENTICATED"
    assert body["request_id"] == response.headers["x-request-id"]


@pytest.mark.parametrize(
    "authorization", ["", "Bearer", "Bearer ", "Basic dXNlcjpwYXNz", "Token abc", "abc"]
)
def test_other_authorization_headers_are_unauthenticated(
    api: TestClient, authorization: str
) -> None:
    response = api.get("/v1/me", headers={"Authorization": authorization})

    assert response.status_code == 401
    assert response.json()["code"] in {"UNAUTHENTICATED", "INVALID_TOKEN"}


def test_a_garbage_token_is_rejected_without_echoing_it(api: TestClient) -> None:
    response = api.get("/v1/me", headers=bearer("definitely.not.ajwt-S3CRET"))

    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_TOKEN"
    assert 'error="invalid_token"' in response.headers["www-authenticate"]
    assert "S3CRET" not in response.text


def test_an_expired_token_is_reported_so_the_client_can_refresh(
    api: TestClient, signing_key: SigningKey
) -> None:
    token = sign_with_key(signing_key, build_claims(sub=uuid.uuid4(), expires_in=-120))

    response = api.get("/v1/me", headers=bearer(token))

    assert response.status_code == 401
    assert response.json()["code"] == "TOKEN_EXPIRED"
    assert "expired" in response.headers["www-authenticate"]


def test_a_token_signed_with_an_unknown_key_is_rejected(api: TestClient) -> None:
    attacker = make_ec_key("attacker-key")
    token = sign_with_key(attacker, build_claims(sub=uuid.uuid4()))

    response = api.get("/v1/me", headers=bearer(token))

    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_TOKEN"


def test_a_token_forged_with_the_right_kid_but_the_wrong_key_is_rejected(
    api: TestClient, signing_key: SigningKey
) -> None:
    forger = make_ec_key(signing_key.kid)
    token = sign_with_key(forger, build_claims(sub=uuid.uuid4()))

    assert api.get("/v1/me", headers=bearer(token)).status_code == 401


def test_a_shared_secret_token_is_refused_when_asymmetric_keys_are_configured(
    api: TestClient,
) -> None:
    token = sign_hs256("x" * 48, build_claims(sub=uuid.uuid4()))

    assert api.get("/v1/me", headers=bearer(token)).status_code == 401


def test_the_anon_key_cannot_be_used_as_a_user_token(
    api: TestClient, signing_key: SigningKey
) -> None:
    claims = build_claims(sub=None, role="anon", audience="anon", email=None)

    response = api.get("/v1/me", headers=bearer(sign_with_key(signing_key, claims)))

    assert response.status_code == 401


def test_the_service_role_key_cannot_be_used_as_a_user_token(
    api: TestClient, signing_key: SigningKey, make_learner: MakeLearner
) -> None:
    claims = build_claims(sub=make_learner().id, role="service_role")

    response = api.get("/v1/me", headers=bearer(sign_with_key(signing_key, claims)))

    assert response.status_code == 401


# --- Authentication is enforced by construction, on every operation ---------------------------


def test_every_v1_operation_rejects_anonymous_requests(api: TestClient) -> None:
    """Walks the real OpenAPI document, so a route added later is covered automatically."""
    operations = [
        (method.upper(), path)
        for path, item in api.get("/openapi.json").json()["paths"].items()
        if path.startswith("/v1")
        for method in item
        if method in {"get", "post", "put", "patch", "delete"}
    ]
    assert len(operations) >= 3  # /v1/me and the goal routes at least

    for method, path in operations:
        concrete = path.replace("{goal_id}", str(uuid.uuid4()))
        response = api.request(
            method, concrete, json={} if method in {"POST", "PUT", "PATCH"} else None
        )

        assert response.status_code == 401, f"{method} {path} answered {response.status_code}"


def test_authentication_is_checked_before_the_request_body(api: TestClient) -> None:
    """An anonymous caller learns nothing about validation rules."""
    response = api.post("/v1/goals", json={"unexpected": "shape"})

    assert response.status_code == 401


# --- Deleted accounts -------------------------------------------------------------------------


def test_a_valid_token_for_a_deleted_account_is_treated_as_signed_out(
    api: TestClient, make_learner: MakeLearner, database_dsn: str
) -> None:
    learner = make_learner()
    admin(database_dsn).execute("delete from auth.users where id = %s", (learner.id,))

    me = api.get("/v1/me", headers=learner.headers)
    create = api.post("/v1/goals", headers=learner.headers, json={"title": "Ghost goal"})

    assert me.status_code == 401
    assert me.json()["code"] == "ACCOUNT_NOT_FOUND"
    assert create.status_code == 401
    assert create.json()["code"] == "ACCOUNT_NOT_FOUND"


# --- Logging never contains credentials -------------------------------------------------------


def test_logs_record_why_a_request_was_rejected_but_never_the_token(
    api: TestClient, signing_key: SigningKey
) -> None:
    token = sign_with_key(signing_key, build_claims(sub=uuid.uuid4(), expires_in=-120))

    with structlog.testing.capture_logs() as logs:
        api.get("/v1/me", headers=bearer(token))

    rejections = [entry for entry in logs if entry["event"] == "auth.rejected"]
    assert rejections
    assert rejections[0]["reason"] == "expired"
    assert token not in repr(logs)


def test_logs_for_authenticated_requests_carry_ids_not_personal_data(
    api: TestClient, make_learner: MakeLearner
) -> None:
    learner = make_learner(display_name="Ada Lovelace")

    with structlog.testing.capture_logs() as logs:
        api.post("/v1/goals", headers=learner.headers, json={"title": "A very private goal title"})

    text = repr(logs)
    assert "goal.created" in text
    assert learner.token not in text
    assert learner.email not in text
    assert "A very private goal title" not in text
    assert "Ada Lovelace" not in text
