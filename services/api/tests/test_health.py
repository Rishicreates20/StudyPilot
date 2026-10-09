from fastapi import FastAPI
from fastapi.testclient import TestClient
from helpers import IsolatedSettings

from app.core.config import AppEnv
from app.main import create_app


def test_healthz_reports_liveness_without_exposing_configuration(client: TestClient) -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "StudyPilot", "version": "0.1.0"}


def test_readyz_is_ready_when_no_dependencies_are_registered(client: TestClient) -> None:
    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {}}


def test_readyz_returns_503_when_a_dependency_check_fails(app: FastAPI, client: TestClient) -> None:
    async def healthy() -> bool:
        return True

    async def unhealthy() -> bool:
        return False

    app.state.readiness_checks = {"cache": healthy, "database": unhealthy}

    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "checks": {"cache": "ok", "database": "fail"},
    }


def test_readyz_treats_a_raising_check_as_failed_without_leaking_the_error(
    app: FastAPI, client: TestClient
) -> None:
    async def exploding() -> bool:
        raise ConnectionError("password=hunter2 host=db.internal")

    app.state.readiness_checks = {"database": exploding}

    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json()["checks"] == {"database": "fail"}
    assert "hunter2" not in response.text


def test_api_docs_are_available_outside_production(client: TestClient) -> None:
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_api_docs_are_disabled_in_production() -> None:
    production = IsolatedSettings(
        app_env=AppEnv.PRODUCTION,
        cors_allowed_origins=["https://app.example.com"],
    )
    with TestClient(create_app(production)) as production_client:
        assert production_client.get("/docs").status_code == 404
        assert production_client.get("/openapi.json").status_code == 404
        assert production_client.get("/healthz").status_code == 200
