"""Small helpers shared by the HTTP-level tests."""

from typing import Any

from fastapi.testclient import TestClient

from conftest import Learner


def create_goal(api: TestClient, learner: Learner, **fields: Any) -> dict[str, Any]:
    """POST a goal for ``learner`` and return the stored goal."""
    response = api.post(
        "/v1/goals", headers=learner.headers, json={"title": "Learn Kubernetes", **fields}
    )
    assert response.status_code == 201, response.text
    return response.json()


def set_status(api: TestClient, learner: Learner, goal_id: str, status: str) -> dict[str, Any]:
    """Move a goal to ``status`` through the API and return the updated goal."""
    response = api.put(
        f"/v1/goals/{goal_id}/status", headers=learner.headers, json={"status": status}
    )
    assert response.status_code == 200, response.text
    return response.json()


def goal_in_status(api: TestClient, learner: Learner, status: str, **fields: Any) -> dict[str, Any]:
    """A goal for ``learner`` currently in ``status`` (every state is one step from active)."""
    goal = create_goal(api, learner, **fields)
    return goal if status == "active" else set_status(api, learner, goal["id"], status)


def errors_by_field(response_json: dict[str, Any]) -> dict[str, str]:
    """Field -> message from a problem+json validation response.

    The ``body.`` prefix is removed and a list item (``languages.0``) is reported against its
    field (``languages``), which is how a form shows it.
    """
    fields: dict[str, str] = {}
    for error in response_json.get("errors", []):
        field = error["field"].removeprefix("body.").split(".")[0]
        fields.setdefault(field, error["message"])
    return fields
