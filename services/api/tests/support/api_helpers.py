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


def generate_roadmap(api: TestClient, dsn: str, learner: Learner, goal_id: str) -> dict[str, Any]:
    """Generate a roadmap for ``goal_id`` with the real worker and return the stored roadmap."""
    from support.worker import clear_queue, run_worker_once

    clear_queue(dsn)  # leftovers from other tests must not be picked up instead of this job
    started = api.post(f"/v1/goals/{goal_id}/roadmaps", headers=learner.headers, json={})
    assert started.status_code == 202, started.text
    assert run_worker_once(dsn) is True
    job = api.get(f"/v1/jobs/{started.json()['id']}", headers=learner.headers).json()
    assert job["status"] == "completed", job
    roadmap = api.get(f"/v1/roadmaps/{job['roadmap_id']}", headers=learner.headers)
    assert roadmap.status_code == 200, roadmap.text
    return roadmap.json()


def topic_ids(roadmap: dict[str, Any]) -> list[str]:
    """The ids of a roadmap's topics, in study order."""
    return [topic["id"] for module in roadmap["modules"] for topic in module["topics"]]
