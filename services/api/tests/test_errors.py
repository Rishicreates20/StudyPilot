from fastapi import FastAPI
from fastapi.testclient import TestClient

PROBLEM_JSON = "application/problem+json"


def test_unknown_route_returns_a_problem_document(client: TestClient) -> None:
    response = client.get("/does-not-exist")
    body = response.json()

    assert response.status_code == 404
    assert response.headers["content-type"].startswith(PROBLEM_JSON)
    assert body["code"] == "NOT_FOUND"
    assert body["status"] == 404
    assert body["title"] == "Not Found"
    assert body["request_id"] == response.headers["X-Request-ID"]


def test_wrong_method_returns_a_problem_document(client: TestClient) -> None:
    response = client.post("/healthz")

    assert response.status_code == 405
    assert response.json()["code"] == "METHOD_NOT_ALLOWED"


def test_validation_errors_list_fields_without_echoing_submitted_values(
    app: FastAPI, client: TestClient
) -> None:
    @app.get("/_test/validate")
    async def validate(limit: int) -> dict[str, int]:  # pyright: ignore[reportUnusedFunction]
        return {"limit": limit}

    response = client.get("/_test/validate", params={"limit": "not-a-number-s3cret"})
    body = response.json()

    assert response.status_code == 422
    assert response.headers["content-type"].startswith(PROBLEM_JSON)
    assert body["code"] == "VALIDATION_ERROR"
    assert body["errors"][0]["field"] == "query.limit"
    assert "s3cret" not in response.text


def test_unexpected_errors_return_a_generic_body_with_a_request_id(
    app: FastAPI, client: TestClient
) -> None:
    @app.get("/_test/boom")
    async def boom() -> None:  # pyright: ignore[reportUnusedFunction]
        raise RuntimeError("database password is hunter2")

    response = client.get("/_test/boom", headers={"X-Request-ID": "req-from-caller-1"})
    body = response.json()

    assert response.status_code == 500
    assert response.headers["content-type"].startswith(PROBLEM_JSON)
    assert body["code"] == "INTERNAL_ERROR"
    assert body["request_id"] == "req-from-caller-1"
    assert response.headers["X-Request-ID"] == "req-from-caller-1"
    assert "hunter2" not in response.text
    assert "Traceback" not in response.text
