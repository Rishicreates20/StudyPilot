"""When dependencies fail: the API degrades safely and leaks nothing about its infrastructure."""

from collections.abc import Mapping
from typing import Any

import pytest
from pydantic import SecretStr

from app.core.config import AppEnv, Settings
from app.main import create_app
from conftest import Learner, new_client
from support.keys import SigningKey, build_claims, sign_with_key, static_jwks_fetcher
from support.settings import (
    TEST_SUPABASE_URL,
    UNREACHABLE_DATABASE_URL,
    IsolatedSettings,
)


def token_for(signing_key: SigningKey, user_id: Any) -> dict[str, str]:
    claims = build_claims(sub=user_id)
    return {"Authorization": f"Bearer {sign_with_key(signing_key, claims)}"}


def settings_with(**overrides: Any) -> Settings:
    values: dict[str, Any] = {"app_env": AppEnv.TEST, "supabase_url": TEST_SUPABASE_URL}
    values.update(overrides)
    return IsolatedSettings(**values)


def test_an_unreachable_database_yields_503_and_leaks_no_connection_details(
    signing_key: SigningKey,
) -> None:
    settings = settings_with(
        database_url=SecretStr(UNREACHABLE_DATABASE_URL), db_pool_timeout_seconds=0.5
    )
    app = create_app(settings, jwks_fetcher=static_jwks_fetcher(signing_key))

    with new_client(app) as client:
        import uuid

        response = client.get("/v1/me", headers=token_for(signing_key, uuid.uuid4()))
        ready = client.get("/readyz")

    assert response.status_code == 503
    assert response.json()["code"] == "SERVICE_UNAVAILABLE"
    assert response.headers["retry-after"] == "5"
    for secret in ("127.0.0.1", "postgres", ":1/", "password"):
        assert secret not in response.text
    assert ready.status_code == 503
    assert ready.json() == {"status": "unavailable", "checks": {"database": "fail"}}


def test_readiness_is_green_when_the_database_answers(
    api: Any,
) -> None:
    response = api.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {"database": "ok"}}


def test_a_missing_database_configuration_is_a_503_not_a_crash(signing_key: SigningKey) -> None:
    import uuid

    app = create_app(settings_with(), jwks_fetcher=static_jwks_fetcher(signing_key))

    with new_client(app) as client:
        response = client.get("/v1/me", headers=token_for(signing_key, uuid.uuid4()))

    assert response.status_code == 503
    assert response.json()["code"] == "DATABASE_NOT_CONFIGURED"


def test_without_supabase_configuration_protected_routes_report_it_clearly() -> None:
    app = create_app(IsolatedSettings(app_env=AppEnv.TEST))

    with new_client(app) as client:
        anonymous = client.get("/v1/me")
        with_token = client.get("/v1/me", headers={"Authorization": "Bearer abc.def.ghi"})

    assert anonymous.status_code == 401  # credentials are checked first
    assert with_token.status_code == 503
    assert with_token.json()["code"] == "AUTH_NOT_CONFIGURED"


def test_an_outage_of_the_signing_key_endpoint_is_503_not_a_false_rejection(
    signing_key: SigningKey, make_learner: Any
) -> None:
    async def failing_fetch() -> Mapping[str, Any]:
        raise ConnectionError("jwks endpoint down: https://secret-host.internal/keys")

    learner: Learner = make_learner()
    settings = settings_with(database_url=SecretStr(UNREACHABLE_DATABASE_URL))
    app = create_app(settings, jwks_fetcher=failing_fetch)

    with new_client(app) as client:
        response = client.get("/v1/me", headers=learner.headers)

    assert response.status_code == 503
    assert response.json()["code"] == "AUTH_UNAVAILABLE"
    assert "secret-host" not in response.text


@pytest.mark.parametrize("origin", ["https://evil.example", "null"])
def test_browsers_on_other_origins_get_no_cors_permission(api: Any, origin: str) -> None:
    response = api.options(
        "/v1/goals",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )

    assert "access-control-allow-origin" not in response.headers


def test_the_configured_web_origin_may_call_the_api_with_a_bearer_token(api: Any) -> None:
    response = api.options(
        "/v1/goals",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    # Bearer tokens, not cookies: credentials are deliberately not allowed cross-origin.
    assert "access-control-allow-credentials" not in response.headers
