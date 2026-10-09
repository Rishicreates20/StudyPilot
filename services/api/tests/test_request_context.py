import re

from fastapi.testclient import TestClient


def test_a_request_id_is_generated_and_returned_when_absent(client: TestClient) -> None:
    response = client.get("/healthz")

    assert re.fullmatch(r"[0-9a-f]{32}", response.headers["X-Request-ID"])


def test_a_well_formed_caller_supplied_request_id_is_propagated(client: TestClient) -> None:
    response = client.get("/healthz", headers={"X-Request-ID": "trace-abc-12345"})

    assert response.headers["X-Request-ID"] == "trace-abc-12345"


def test_a_malformed_caller_supplied_request_id_is_replaced(client: TestClient) -> None:
    for supplied in ("short", "has spaces in it", "x" * 200, "semi;colon;injected"):
        response = client.get("/healthz", headers={"X-Request-ID": supplied})

        assert response.headers["X-Request-ID"] != supplied
        assert re.fullmatch(r"[0-9a-f]{32}", response.headers["X-Request-ID"])


def test_cors_preflight_from_an_allowed_origin_is_accepted(client: TestClient) -> None:
    response = client.options(
        "/healthz",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "X-Request-ID" in response.headers


def test_cors_preflight_from_an_unknown_origin_is_refused(client: TestClient) -> None:
    response = client.options(
        "/healthz",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )

    assert "access-control-allow-origin" not in response.headers
