"""Helpers for driving quizzes through the HTTP API with the real worker (no mocks)."""

import re
from typing import Any

from fastapi.testclient import TestClient
from httpx2 import Response

from conftest import Learner
from support.api_helpers import create_goal, generate_roadmap, topic_ids
from support.database import admin
from support.worker import clear_queue, run_worker_once


def write_lesson(api: TestClient, dsn: str, learner: Learner, item_id: str) -> dict[str, Any]:
    """Start a lesson for ``item_id`` and run it to completion. Returns the finished job."""
    clear_queue(dsn)
    response = api.post(f"/v1/roadmap-items/{item_id}/lessons", headers=learner.headers, json={})
    assert response.status_code == 202, response.text
    assert run_worker_once(dsn) is True
    job = api.get(f"/v1/jobs/{response.json()['id']}", headers=learner.headers).json()
    assert job["status"] == "completed", job
    return job


def start_quiz(
    api: TestClient,
    learner: Learner,
    item_id: str,
    /,
    *,
    headers: dict[str, str] | None = None,
    **body: Any,
) -> Response:
    return api.post(
        f"/v1/roadmap-items/{item_id}/quizzes",
        headers={**learner.headers, **(headers or {})},
        json=body,
    )


def write_quiz(
    api: TestClient, dsn: str, learner: Learner, item_id: str, /, **body: Any
) -> dict[str, Any]:
    """Start a quiz and run it to completion. Returns the finished job (it names the quiz)."""
    clear_queue(dsn)
    response = start_quiz(api, learner, item_id, **body)
    assert response.status_code == 202, response.text
    assert run_worker_once(dsn) is True
    job = api.get(f"/v1/jobs/{response.json()['id']}", headers=learner.headers).json()
    assert job["status"] == "completed", job
    assert job["quiz_id"] is not None
    return job


def read_quiz(api: TestClient, learner: Learner, quiz_id: str) -> dict[str, Any]:
    response = api.get(f"/v1/quizzes/{quiz_id}", headers=learner.headers)
    assert response.status_code == 200, response.text
    return response.json()


def submit(
    api: TestClient,
    learner: Learner,
    quiz_id: str,
    answers: list[dict[str, Any]],
    /,
    *,
    key: str | None = None,
    **extra: Any,
) -> Response:
    headers = dict(learner.headers)
    if key is not None:
        headers["Idempotency-Key"] = key
    return api.post(
        f"/v1/quizzes/{quiz_id}/attempts", headers=headers, json={"answers": answers, **extra}
    )


def _key_row(dsn: str, question_id: str) -> dict[str, Any]:
    row = admin(dsn).fetchone(
        "select * from public.question_answer_keys where question_id = %s", (question_id,)
    )
    assert row is not None
    return dict(row)


def answer_all(
    dsn: str, quiz: dict[str, Any], *, right: bool, short_answers: str = "right"
) -> list[dict[str, Any]]:
    """Answers for every question: the right options (or a wrong one each) and, for short answers,
    text that covers every rubric point ("right") or none of them ("wrong") or nothing ("blank")."""
    answers: list[dict[str, Any]] = []
    for question in quiz["questions"]:
        key = _key_row(dsn, question["id"])
        if question["kind"] == "short_answer":
            if short_answers == "blank":
                continue
            if short_answers == "right":
                text = " ".join(point["text"] for point in key["rubric"]["points"])
            else:
                text = "Banana pyjamas on a Tuesday."
            answers.append({"question_id": question["id"], "text": text})
            continue
        correct = key["correct_option_id"]
        if right:
            chosen = correct
        else:
            chosen = next(o["id"] for o in question["options"] if o["id"] != correct)
        answers.append({"question_id": question["id"], "option_id": chosen})
    return answers


def finish_grading(api: TestClient, dsn: str, learner: Learner, attempt_id: str) -> dict[str, Any]:
    """Run the queued grading job (if any) and return the attempt's result."""
    assert run_worker_once(dsn) is True
    response = api.get(f"/v1/quiz-attempts/{attempt_id}", headers=learner.headers)
    assert response.status_code == 200, response.text
    return response.json()


def take_quiz(
    api: TestClient,
    dsn: str,
    learner: Learner,
    item_id: str,
    *,
    right: bool,
    short_answers: str = "right",
    purpose: str = "check",
) -> dict[str, Any]:
    """Write a quiz, answer it, submit it and (if needed) mark the short answers.

    Returns the final result of the attempt."""
    job = write_quiz(api, dsn, learner, item_id, purpose=purpose)
    quiz = read_quiz(api, learner, job["quiz_id"])
    clear_queue(dsn)
    response = submit(
        api, learner, quiz["id"], answer_all(dsn, quiz, right=right, short_answers=short_answers)
    )
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    if result["status"] == "grading":
        result = finish_grading(api, dsn, learner, result["id"])
    return result


class Seeded:
    """Alice with a goal, a roadmap and a lesson for each of her first topics."""

    def __init__(self, api: TestClient, dsn: str, learner: Learner, *, lessons: int = 2) -> None:
        self.learner = learner
        goal = create_goal(api, learner)
        self.goal: str = goal["id"]
        self.roadmap = generate_roadmap(api, dsn, learner, self.goal)
        self.topics = topic_ids(self.roadmap)
        for item in self.topics[:lessons]:
            write_lesson(api, dsn, learner, item)


def contains_key(value: Any, names: set[str]) -> bool:
    """Whether any mapping inside ``value`` has one of the given keys."""
    if isinstance(value, dict):
        return any(
            key in names or contains_key(child, names)
            for key, child in value.items()  # pyright: ignore[reportUnknownVariableType]
        )
    if isinstance(value, list):
        return any(contains_key(child, names) for child in value)  # pyright: ignore[reportUnknownVariableType]
    return False


UUID_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
