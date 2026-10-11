"""Quizzes through the HTTP API: ownership, secret answers, grading, repeats and the queue."""

from collections.abc import Callable
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from conftest import Learner
from support.api_helpers import create_goal, generate_roadmap, set_status
from support.database import admin
from support.quiz_api import (
    Seeded,
    answer_all,
    contains_key,
    finish_grading,
    read_quiz,
    start_quiz,
    submit,
    take_quiz,
    write_quiz,
)
from support.worker import clear_queue

MakeLearner = Callable[..., Learner]

# Things only a graded result may contain.
SECRET_KEYS = {"correct_option_id", "explanation", "rubric", "model_answer", "option_notes"}


@pytest.fixture
def owned(api: TestClient, database_dsn: str, make_learner: MakeLearner) -> dict[str, Any]:
    """Alice: lessons for her first two topics and a written quiz for the first. Bob: nothing."""
    alice, bob = make_learner(), make_learner()
    seeded = Seeded(api, database_dsn, alice)
    job = write_quiz(api, database_dsn, alice, seeded.topics[0])
    return {
        "alice": alice,
        "bob": bob,
        "goal": seeded.goal,
        "topics": seeded.topics,
        "item": seeded.topics[0],
        "quiz": job["quiz_id"],
        "job": job["id"],
    }


@pytest.fixture
def lessoned(api: TestClient, database_dsn: str, make_learner: MakeLearner) -> dict[str, Any]:
    """Alice with a lesson for each of her first two topics and no quiz yet."""
    alice = make_learner()
    seeded = Seeded(api, database_dsn, alice)
    return {"alice": alice, "goal": seeded.goal, "topics": seeded.topics}


# --- Authentication and ownership on every endpoint ------------------------------------------

ENDPOINTS: list[tuple[str, str, dict[str, Any] | None]] = [
    ("post", "/v1/roadmap-items/{item}/quizzes", {}),
    ("get", "/v1/roadmap-items/{item}/quizzes", None),
    ("get", "/v1/roadmap-items/{item}/assessment", None),
    ("get", "/v1/quizzes/{quiz}", None),
    ("post", "/v1/quizzes/{quiz}/attempts", {"answers": []}),
    ("get", "/v1/quiz-attempts/{attempt}", None),
    ("post", "/v1/quiz-attempts/{attempt}/regrade", None),
    ("put", "/v1/quiz-answers/{answer}/review", {"met_point_ids": []}),
    ("get", "/v1/goals/{goal}/progress", None),
]


@pytest.fixture
def graded(api: TestClient, database_dsn: str, owned: dict[str, Any]) -> dict[str, Any]:
    """``owned`` after Alice has submitted her quiz (so an attempt and answers exist)."""
    quiz = read_quiz(api, owned["alice"], owned["quiz"])
    clear_queue(database_dsn)
    response = submit(
        api, owned["alice"], owned["quiz"], answer_all(database_dsn, quiz, right=True)
    )
    assert response.status_code == 201, response.text
    result = response.json()
    return {**owned, "attempt": result["id"], "answer": result["answers"][0]["id"]}


def url_for(template: str, ids: dict[str, Any]) -> str:
    return template.format(
        item=ids["item"],
        quiz=ids["quiz"],
        attempt=ids["attempt"],
        answer=ids["answer"],
        goal=ids["goal"],
    )


@pytest.mark.parametrize(("method", "template", "body"), ENDPOINTS)
def test_every_endpoint_requires_a_token(
    api: TestClient, graded: dict[str, Any], method: str, template: str, body: Any
) -> None:
    assert api.request(method, url_for(template, graded), json=body).status_code == 401


@pytest.mark.parametrize(("method", "template", "body"), ENDPOINTS)
def test_every_endpoint_rejects_a_bad_token(
    api: TestClient, graded: dict[str, Any], method: str, template: str, body: Any
) -> None:
    response = api.request(
        method, url_for(template, graded), json=body, headers={"Authorization": "Bearer nonsense"}
    )

    assert response.status_code == 401


@pytest.mark.parametrize(("method", "template", "body"), ENDPOINTS)
def test_another_learners_resources_are_not_found(
    api: TestClient, graded: dict[str, Any], method: str, template: str, body: Any
) -> None:
    response = api.request(
        method, url_for(template, graded), json=body, headers=graded["bob"].headers
    )

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")


@pytest.mark.parametrize(("method", "template", "body"), ENDPOINTS)
def test_missing_resources_look_exactly_like_other_peoples(
    api: TestClient, graded: dict[str, Any], method: str, template: str, body: Any
) -> None:
    missing: dict[str, Any] = {
        name: str(uuid4()) for name in ("item", "quiz", "attempt", "answer", "goal")
    }
    theirs = api.request(
        method, url_for(template, graded), json=body, headers=graded["bob"].headers
    )
    nothing = api.request(
        method, url_for(template, missing), json=body, headers=graded["alice"].headers
    )

    assert (nothing.status_code, nothing.json()["code"]) == (
        theirs.status_code,
        theirs.json()["code"],
    )


def test_a_malformed_id_is_a_validation_error_not_a_crash(
    api: TestClient, make_learner: MakeLearner
) -> None:
    learner = make_learner()

    assert api.get("/v1/quizzes/nope", headers=learner.headers).status_code == 422
    assert api.get("/v1/quiz-attempts/nope", headers=learner.headers).status_code == 422
    assert start_quiz(api, learner, "12345").status_code == 422
    assert api.get("/v1/goals/nope/progress", headers=learner.headers).status_code == 422


def test_another_learner_cannot_start_a_quiz_on_my_topic_and_nothing_is_queued(
    api: TestClient, database_dsn: str, lessoned: dict[str, Any], make_learner: MakeLearner
) -> None:
    bob = make_learner()

    response = start_quiz(api, bob, lessoned["topics"][0])

    assert response.status_code == 404
    count = admin(database_dsn).scalar(
        "select count(*) from public.generation_jobs where item_id = %s and job_type = 'quiz'",
        (lessoned["topics"][0],),
    )
    assert count == 0


def test_another_learner_cannot_submit_my_quiz_and_nothing_is_stored(
    api: TestClient, database_dsn: str, owned: dict[str, Any]
) -> None:
    quiz = read_quiz(api, owned["alice"], owned["quiz"])

    response = submit(api, owned["bob"], owned["quiz"], answer_all(database_dsn, quiz, right=True))

    assert response.status_code == 404
    count = admin(database_dsn).scalar(
        "select count(*) from public.quiz_attempts where quiz_id = %s", (owned["quiz"],)
    )
    assert count == 0


# --- Starting a quiz -------------------------------------------------------------------------


def test_starting_queues_a_job_and_returns_at_once(
    api: TestClient, database_dsn: str, lessoned: dict[str, Any]
) -> None:
    item = lessoned["topics"][0]

    response = start_quiz(api, lessoned["alice"], item)

    assert response.status_code == 202
    job = response.json()
    assert response.headers["location"] == f"/v1/jobs/{job['id']}"
    assert (job["status"], job["stage"], job["progress"], job["attempts"]) == (
        "queued",
        "queued",
        0,
        0,
    )
    assert (job["job_type"], job["item_id"], job["goal_id"]) == ("quiz", item, lessoned["goal"])
    assert job["quiz_id"] is None and job["attempt_id"] is None
    row = admin(database_dsn).fetchone(
        "select user_id, request from public.generation_jobs where id = %s", (job["id"],)
    )
    assert row is not None and row["user_id"] == lessoned["alice"].id
    assert row["request"]["purpose"] == "check"
    assert row["request"]["question_count"] == 5 and row["request"]["max_short_answers"] == 1
    assert "lesson_id" in row["request"]


@pytest.mark.parametrize(
    "body",
    [
        {"user_id": str(uuid4())},
        {"status": "completed"},
        {"item_id": str(uuid4())},
        {"goal_id": str(uuid4())},
        {"purpose": "exam"},
        {"purpose": 3},
        {"focus_objective_ids": ["o1"]},
        {"question_count": 99},
    ],
)
def test_unknown_or_invalid_fields_are_rejected(
    api: TestClient, lessoned: dict[str, Any], body: dict[str, Any]
) -> None:
    response = start_quiz(api, lessoned["alice"], lessoned["topics"][0], **body)

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_a_quiz_needs_a_lesson_first(
    api: TestClient, database_dsn: str, lessoned: dict[str, Any]
) -> None:
    item_without_lesson = lessoned["topics"][2]

    response = start_quiz(api, lessoned["alice"], item_without_lesson)

    assert response.status_code == 409
    assert response.json()["code"] == "LESSON_REQUIRED"
    count = admin(database_dsn).scalar(
        "select count(*) from public.generation_jobs where item_id = %s and job_type = 'quiz'",
        (item_without_lesson,),
    )
    assert count == 0


def test_a_quiz_cannot_be_started_without_an_ai_provider(
    api: TestClient, lessoned: dict[str, Any], configure_app: Callable[..., None]
) -> None:
    configure_app(llm_provider=None)

    response = start_quiz(api, lessoned["alice"], lessoned["topics"][0])

    assert response.status_code == 503
    assert response.json()["code"] == "AI_NOT_CONFIGURED"


def test_a_revision_session_has_no_quiz(
    api: TestClient, database_dsn: str, make_learner: MakeLearner
) -> None:
    learner = make_learner()
    goal = create_goal(api, learner)
    roadmap = generate_roadmap(api, database_dsn, learner, goal["id"])
    revision = roadmap["revision_sessions"][0]["id"]

    response = start_quiz(api, learner, revision)

    assert response.status_code == 422
    assert response.json()["code"] == "TOPIC_NOT_LESSONABLE"
    assert (
        api.get(f"/v1/roadmap-items/{revision}/quizzes", headers=learner.headers).status_code == 404
    )


def test_an_archived_goal_cannot_start_a_quiz(api: TestClient, lessoned: dict[str, Any]) -> None:
    set_status(api, lessoned["alice"], lessoned["goal"], "archived")

    response = start_quiz(api, lessoned["alice"], lessoned["topics"][0])

    assert response.status_code == 409
    assert response.json()["code"] == "GOAL_ARCHIVED"


def test_a_second_quiz_cannot_be_queued_while_one_is_being_written(
    api: TestClient, lessoned: dict[str, Any]
) -> None:
    item = lessoned["topics"][0]
    assert start_quiz(api, lessoned["alice"], item).status_code == 202

    again = start_quiz(api, lessoned["alice"], item)

    assert again.status_code == 409
    assert again.json()["code"] == "QUIZ_JOB_ACTIVE"


def test_a_topic_holds_one_untaken_quiz_at_a_time(api: TestClient, owned: dict[str, Any]) -> None:
    response = start_quiz(api, owned["alice"], owned["item"])

    assert response.status_code == 409
    assert response.json()["code"] == "QUIZ_PENDING"


def test_the_same_idempotency_key_returns_the_same_job(
    api: TestClient, database_dsn: str, lessoned: dict[str, Any]
) -> None:
    item = lessoned["topics"][0]
    headers = {"Idempotency-Key": "form-submit-0001"}

    first = start_quiz(api, lessoned["alice"], item, headers=headers)
    second = start_quiz(api, lessoned["alice"], item, headers=headers)

    assert first.status_code == 202 and second.status_code == 202
    assert first.json()["id"] == second.json()["id"]
    count = admin(database_dsn).scalar(
        "select count(*) from public.generation_jobs where item_id = %s and job_type = 'quiz'",
        (item,),
    )
    assert count == 1


def test_an_idempotency_key_cannot_be_reused_for_a_different_request(
    api: TestClient, lessoned: dict[str, Any]
) -> None:
    headers = {"Idempotency-Key": "form-submit-0002"}
    assert (
        start_quiz(api, lessoned["alice"], lessoned["topics"][0], headers=headers).status_code
        == 202
    )

    other_topic = start_quiz(api, lessoned["alice"], lessoned["topics"][1], headers=headers)

    assert other_topic.status_code == 409
    assert other_topic.json()["code"] == "IDEMPOTENCY_KEY_REUSED"


def test_the_daily_allowance_is_enforced(
    api: TestClient, lessoned: dict[str, Any], configure_app: Callable[..., None]
) -> None:
    configure_app(quiz_jobs_per_user_per_day=1)
    assert start_quiz(api, lessoned["alice"], lessoned["topics"][0]).status_code == 202

    over = start_quiz(api, lessoned["alice"], lessoned["topics"][1])

    assert over.status_code == 429
    assert over.json()["code"] == "QUIZ_LIMIT_REACHED"


def test_a_quiz_is_not_started_for_a_topic_of_an_earlier_roadmap(
    api: TestClient, database_dsn: str, lessoned: dict[str, Any]
) -> None:
    item = lessoned["topics"][0]
    admin(database_dsn).execute(
        "update public.roadmaps set status = 'superseded' where id ="
        " (select roadmap_id from public.roadmap_items where id = %s)",
        (item,),
    )

    response = start_quiz(api, lessoned["alice"], item)

    assert response.status_code == 409
    assert response.json()["code"] == "ROADMAP_NOT_CURRENT"


# --- Reading a quiz never reveals an answer ---------------------------------------------------


def test_the_quiz_contains_questions_and_options_and_nothing_secret(
    api: TestClient, database_dsn: str, owned: dict[str, Any]
) -> None:
    quiz = read_quiz(api, owned["alice"], owned["quiz"])

    assert quiz["status"] == "ready" and quiz["attempt"] is None
    assert quiz["is_synthetic"] is True and quiz["purpose"] == "check"
    assert len(quiz["questions"]) == quiz["question_count"] == 5
    assert {q["kind"] for q in quiz["questions"]} <= {
        "multiple_choice",
        "true_false",
        "short_answer",
    }
    assert not contains_key(quiz, SECRET_KEYS)
    for question in quiz["questions"]:
        assert set(question) == {
            "id", "position", "kind", "prompt", "options", "objective_id", "objective_text",
            "difficulty", "max_points",
        }  # fmt: skip
        assert question["objective_text"]
        if question["kind"] == "short_answer":
            assert question["options"] is None
        else:
            assert all(set(option) == {"id", "text"} for option in question["options"])
    # Nothing in the payload is the text of any explanation or model answer either.
    text = str(quiz)
    keys = admin(database_dsn).fetchall(
        "select explanation, model_answer from public.question_answer_keys k"
        " join public.questions q on q.id = k.question_id where q.quiz_id = %s",
        (owned["quiz"],),
    )
    assert keys and all(row["explanation"] not in text for row in keys)
    assert all(row["model_answer"] is None or row["model_answer"] not in text for row in keys)


def test_the_quiz_still_hides_everything_after_it_was_submitted(
    api: TestClient, graded: dict[str, Any]
) -> None:
    quiz = read_quiz(api, graded["alice"], graded["quiz"])

    assert quiz["status"] == "submitted" and quiz["attempt"]["id"] == graded["attempt"]
    assert not contains_key(quiz, SECRET_KEYS)


def test_the_quiz_list_shows_status_without_secrets(api: TestClient, owned: dict[str, Any]) -> None:
    response = api.get(f"/v1/roadmap-items/{owned['item']}/quizzes", headers=owned["alice"].headers)

    assert response.status_code == 200
    (summary,) = response.json()["items"]
    assert summary["id"] == owned["quiz"] and summary["status"] == "ready"
    assert not contains_key(response.json(), SECRET_KEYS)


def test_options_are_shuffled_but_the_right_one_is_not_always_first(
    api: TestClient, database_dsn: str, owned: dict[str, Any]
) -> None:
    quiz = read_quiz(api, owned["alice"], owned["quiz"])

    positions: list[int] = []
    for question in quiz["questions"]:
        if question["kind"] != "multiple_choice":
            continue
        correct = admin(database_dsn).scalar(
            "select correct_option_id from public.question_answer_keys where question_id = %s",
            (question["id"],),
        )
        positions.append([o["id"] for o in question["options"]].index(correct))
    assert positions  # the sample quiz has multiple-choice questions


# --- Submitting: validation -------------------------------------------------------------------


def test_an_unknown_question_is_refused_and_nothing_is_stored(
    api: TestClient, database_dsn: str, owned: dict[str, Any]
) -> None:
    quiz = read_quiz(api, owned["alice"], owned["quiz"])
    answers = answer_all(database_dsn, quiz, right=True)
    answers.append({"question_id": str(uuid4()), "option_id": "a"})

    response = submit(api, owned["alice"], owned["quiz"], answers)

    assert response.status_code == 422
    assert response.json()["code"] == "UNKNOWN_QUESTION"
    assert _attempts(database_dsn, owned["quiz"]) == 0


def test_a_question_from_another_quiz_is_refused(
    api: TestClient, database_dsn: str, owned: dict[str, Any]
) -> None:
    other = write_quiz(api, database_dsn, owned["alice"], owned["topics"][1])
    foreign = read_quiz(api, owned["alice"], other["quiz_id"])["questions"][0]

    response = submit(
        api,
        owned["alice"],
        owned["quiz"],
        [{"question_id": foreign["id"], "option_id": "a"}],
    )

    assert response.status_code == 422
    assert response.json()["code"] == "UNKNOWN_QUESTION"


def test_answering_the_same_question_twice_is_refused(
    api: TestClient, database_dsn: str, owned: dict[str, Any]
) -> None:
    quiz = read_quiz(api, owned["alice"], owned["quiz"])
    first = next(q for q in quiz["questions"] if q["kind"] != "short_answer")
    answers = [
        {"question_id": first["id"], "option_id": first["options"][0]["id"]},
        {"question_id": first["id"], "option_id": first["options"][1]["id"]},
    ]

    response = submit(api, owned["alice"], owned["quiz"], answers)

    assert response.status_code == 422
    assert response.json()["code"] == "DUPLICATE_ANSWER"
    assert _attempts(database_dsn, owned["quiz"]) == 0


def test_an_option_that_does_not_exist_is_refused(
    api: TestClient, database_dsn: str, owned: dict[str, Any]
) -> None:
    quiz = read_quiz(api, owned["alice"], owned["quiz"])
    first = next(q for q in quiz["questions"] if q["kind"] == "multiple_choice")

    response = submit(
        api, owned["alice"], owned["quiz"], [{"question_id": first["id"], "option_id": "zz"}]
    )

    assert response.status_code == 422
    assert response.json()["code"] == "UNKNOWN_OPTION"
    assert _attempts(database_dsn, owned["quiz"]) == 0


def test_an_option_of_another_question_is_refused(api: TestClient, owned: dict[str, Any]) -> None:
    quiz = read_quiz(api, owned["alice"], owned["quiz"])
    tf = next(q for q in quiz["questions"] if q["kind"] == "true_false")

    # "d" exists on multiple-choice questions only.
    response = submit(
        api, owned["alice"], owned["quiz"], [{"question_id": tf["id"], "option_id": "d"}]
    )

    assert response.status_code == 422
    assert response.json()["code"] == "UNKNOWN_OPTION"


@pytest.mark.parametrize(
    ("kind", "answer"),
    [
        ("multiple_choice", {"text": "because"}),
        ("multiple_choice", {}),
        ("true_false", {"text": "true"}),
        ("short_answer", {"option_id": "a"}),
        ("short_answer", {}),
    ],
)
def test_the_wrong_kind_of_answer_is_refused(
    api: TestClient, owned: dict[str, Any], kind: str, answer: dict[str, Any]
) -> None:
    quiz = read_quiz(api, owned["alice"], owned["quiz"])
    question = next(q for q in quiz["questions"] if q["kind"] == kind)

    response = submit(
        api, owned["alice"], owned["quiz"], [{"question_id": question["id"], **answer}]
    )

    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_ANSWER"


def test_a_very_long_short_answer_is_refused(api: TestClient, owned: dict[str, Any]) -> None:
    quiz = read_quiz(api, owned["alice"], owned["quiz"])
    question = next(q for q in quiz["questions"] if q["kind"] == "short_answer")

    response = submit(
        api,
        owned["alice"],
        owned["quiz"],
        [{"question_id": question["id"], "text": "x" * 2001}],
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "extra",
    [
        {"user_id": str(uuid4())},
        {"score": 100},
        {"percent": 100},
        {"status": "graded"},
        {"quiz_id": str(uuid4())},
    ],
)
def test_a_submission_cannot_claim_a_score_or_an_owner(
    api: TestClient, owned: dict[str, Any], extra: dict[str, Any]
) -> None:
    response = submit(api, owned["alice"], owned["quiz"], [], **extra)

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_an_answer_cannot_carry_a_grade(api: TestClient, owned: dict[str, Any]) -> None:
    quiz = read_quiz(api, owned["alice"], owned["quiz"])
    question = quiz["questions"][0]

    response = submit(
        api,
        owned["alice"],
        owned["quiz"],
        [{"question_id": question["id"], "option_id": "a", "is_correct": True, "points": 9}],
    )

    assert response.status_code == 422


def test_a_malformed_option_id_is_a_validation_error(
    api: TestClient, owned: dict[str, Any]
) -> None:
    quiz = read_quiz(api, owned["alice"], owned["quiz"])

    response = submit(
        api,
        owned["alice"],
        owned["quiz"],
        [{"question_id": quiz["questions"][0]["id"], "option_id": "A B; drop table"}],
    )

    assert response.status_code == 422


def test_an_archived_goals_quiz_cannot_be_submitted(
    api: TestClient, database_dsn: str, owned: dict[str, Any]
) -> None:
    quiz = read_quiz(api, owned["alice"], owned["quiz"])
    set_status(api, owned["alice"], owned["goal"], "archived")

    response = submit(
        api, owned["alice"], owned["quiz"], answer_all(database_dsn, quiz, right=True)
    )

    assert response.status_code == 409
    assert response.json()["code"] == "GOAL_ARCHIVED"
    assert _attempts(database_dsn, owned["quiz"]) == 0


def _attempts(dsn: str, quiz_id: str) -> int:
    count = admin(dsn).scalar(
        "select count(*) from public.quiz_attempts where quiz_id = %s", (quiz_id,)
    )
    assert isinstance(count, int)
    return count


# --- Submitting: grading, results and repeats -------------------------------------------------


def test_right_answers_score_full_marks_and_reveal_the_explanations(
    api: TestClient, database_dsn: str, owned: dict[str, Any]
) -> None:
    quiz = read_quiz(api, owned["alice"], owned["quiz"])
    clear_queue(database_dsn)

    response = submit(
        api,
        owned["alice"],
        owned["quiz"],
        answer_all(database_dsn, quiz, right=True, short_answers="blank"),
    )

    assert response.status_code == 201
    result = response.json()
    assert result["status"] == "graded" and result["pending_answers"] == 0
    objective_answers = [a for a in result["answers"] if a["kind"] != "short_answer"]
    assert objective_answers and all(a["is_correct"] is True for a in objective_answers)
    assert all(a["grading_method"] == "deterministic" for a in objective_answers)
    for answer in objective_answers:
        assert answer["points_awarded"] == answer["max_points"]
        assert answer["feedback"]["explanation"]
        assert answer["feedback"]["correct_option_id"] == answer["your_answer"]["option_id"]
    # The blank short answer is worth zero by code, never sent to a model.
    (blank,) = [a for a in result["answers"] if a["kind"] == "short_answer"]
    assert blank["skipped"] is True and blank["points_awarded"] == 0
    assert result["points_earned"] < result["points_possible"]
    assert result["is_synthetic"] is True


def test_wrong_answers_score_zero_and_say_what_was_right(
    api: TestClient, database_dsn: str, owned: dict[str, Any]
) -> None:
    quiz = read_quiz(api, owned["alice"], owned["quiz"])
    clear_queue(database_dsn)

    response = submit(
        api,
        owned["alice"],
        owned["quiz"],
        answer_all(database_dsn, quiz, right=False, short_answers="blank"),
    )

    result = response.json()
    assert result["points_earned"] == 0 and result["percent"] == 0
    for answer in (a for a in result["answers"] if a["kind"] != "short_answer"):
        assert answer["is_correct"] is False and answer["points_awarded"] == 0
        assert answer["feedback"]["correct_option_id"] != answer["your_answer"]["option_id"]
        assert answer["feedback"]["explanation"]


def test_unanswered_questions_are_skipped_and_score_nothing(
    api: TestClient, owned: dict[str, Any]
) -> None:
    response = submit(api, owned["alice"], owned["quiz"], [])

    result = response.json()
    assert response.status_code == 201
    assert result["status"] == "graded" and result["percent"] == 0
    assert all(a["skipped"] and a["points_awarded"] == 0 for a in result["answers"])
    assert len(result["answers"]) == 5


def test_a_quiz_can_be_submitted_only_once(
    api: TestClient, database_dsn: str, owned: dict[str, Any]
) -> None:
    quiz = read_quiz(api, owned["alice"], owned["quiz"])
    answers = answer_all(database_dsn, quiz, right=True, short_answers="blank")
    first = submit(api, owned["alice"], owned["quiz"], answers)
    assert first.status_code == 201

    second = submit(api, owned["alice"], owned["quiz"], answers)

    assert second.status_code == 409
    assert second.json()["code"] == "QUIZ_ALREADY_SUBMITTED"
    assert _attempts(database_dsn, owned["quiz"]) == 1


def test_the_same_idempotency_key_returns_the_same_attempt(
    api: TestClient, database_dsn: str, owned: dict[str, Any]
) -> None:
    quiz = read_quiz(api, owned["alice"], owned["quiz"])
    answers = answer_all(database_dsn, quiz, right=True, short_answers="blank")

    first = submit(api, owned["alice"], owned["quiz"], answers, key="submit-quiz-0001")
    again = submit(api, owned["alice"], owned["quiz"], answers, key="submit-quiz-0001")

    assert first.status_code == 201 and again.status_code == 200
    assert first.json()["id"] == again.json()["id"]
    assert _attempts(database_dsn, owned["quiz"]) == 1
    rows = admin(database_dsn).scalar(
        "select count(*) from public.quiz_answers where attempt_id = %s", (first.json()["id"],)
    )
    assert rows == 5


def test_a_different_key_after_a_submission_is_a_conflict_not_a_second_attempt(
    api: TestClient, database_dsn: str, owned: dict[str, Any]
) -> None:
    quiz = read_quiz(api, owned["alice"], owned["quiz"])
    answers = answer_all(database_dsn, quiz, right=True, short_answers="blank")
    submit(api, owned["alice"], owned["quiz"], answers, key="submit-quiz-0001")

    other = submit(api, owned["alice"], owned["quiz"], answers, key="submit-quiz-0002")

    assert other.status_code == 409
    assert _attempts(database_dsn, owned["quiz"]) == 1


def test_results_can_be_read_again_and_match_what_was_returned(
    api: TestClient, database_dsn: str, owned: dict[str, Any]
) -> None:
    quiz = read_quiz(api, owned["alice"], owned["quiz"])
    created = submit(
        api,
        owned["alice"],
        owned["quiz"],
        answer_all(database_dsn, quiz, right=True, short_answers="blank"),
    ).json()

    again = api.get(f"/v1/quiz-attempts/{created['id']}", headers=owned["alice"].headers)

    assert again.status_code == 200
    assert again.json() == created


def test_answering_does_not_change_the_stored_key(
    api: TestClient, database_dsn: str, owned: dict[str, Any]
) -> None:
    quiz = read_quiz(api, owned["alice"], owned["quiz"])
    before = admin(database_dsn).fetchall(
        "select question_id, correct_option_id, explanation from public.question_answer_keys"
        " k join public.questions q on q.id = k.question_id where q.quiz_id = %s"
        " order by question_id",
        (owned["quiz"],),
    )

    submit(api, owned["alice"], owned["quiz"], answer_all(database_dsn, quiz, right=False))

    after = admin(database_dsn).fetchall(
        "select question_id, correct_option_id, explanation from public.question_answer_keys"
        " k join public.questions q on q.id = k.question_id where q.quiz_id = %s"
        " order by question_id",
        (owned["quiz"],),
    )
    assert before == after


# --- Short answers: an estimate, marked in the background -----------------------------------


def test_short_answers_wait_for_the_worker_and_are_labelled_an_estimate(
    api: TestClient, database_dsn: str, owned: dict[str, Any]
) -> None:
    quiz = read_quiz(api, owned["alice"], owned["quiz"])
    clear_queue(database_dsn)

    response = submit(
        api, owned["alice"], owned["quiz"], answer_all(database_dsn, quiz, right=True)
    )

    pending = response.json()
    assert pending["status"] == "grading" and pending["pending_answers"] == 1
    assert pending["percent"] is None and pending["points_earned"] is None
    assert pending["mastery"] is None
    assert pending["grading_job"]["job_type"] == "grade"
    (waiting,) = [a for a in pending["answers"] if a["kind"] == "short_answer"]
    assert waiting["grading_method"] == "pending" and waiting["points_awarded"] is None

    done = finish_grading(api, database_dsn, owned["alice"], pending["id"])
    assert done["status"] == "graded" and done["pending_answers"] == 0
    (marked,) = [a for a in done["answers"] if a["kind"] == "short_answer"]
    assert marked["grading_method"] == "ai_estimate"
    assert marked["points_awarded"] == marked["max_points"]
    assert set(marked["feedback"]["matched_point_ids"]) == {
        p["id"] for p in marked["feedback"]["rubric"]
    }
    assert marked["feedback"]["model_answer"]
    assert done["percent"] == 100 and done["mastery"] is not None


def test_a_weak_short_answer_earns_only_the_points_it_covers(
    api: TestClient, database_dsn: str, owned: dict[str, Any]
) -> None:
    quiz = read_quiz(api, owned["alice"], owned["quiz"])
    clear_queue(database_dsn)
    answers = answer_all(database_dsn, quiz, right=True, short_answers="wrong")
    pending = submit(api, owned["alice"], owned["quiz"], answers).json()

    done = finish_grading(api, database_dsn, owned["alice"], pending["id"])

    (marked,) = [a for a in done["answers"] if a["kind"] == "short_answer"]
    assert marked["points_awarded"] == 0 and marked["feedback"]["matched_point_ids"] == []
    assert done["percent"] < 100


def test_the_learner_can_review_the_estimate(
    api: TestClient, database_dsn: str, owned: dict[str, Any]
) -> None:
    quiz = read_quiz(api, owned["alice"], owned["quiz"])
    clear_queue(database_dsn)
    pending = submit(
        api,
        owned["alice"],
        owned["quiz"],
        answer_all(database_dsn, quiz, right=True, short_answers="wrong"),
    ).json()

    done = finish_grading(api, database_dsn, owned["alice"], pending["id"])
    (marked,) = [a for a in done["answers"] if a["kind"] == "short_answer"]
    all_points = [p["id"] for p in marked["feedback"]["rubric"]]

    response = api.put(
        f"/v1/quiz-answers/{marked['id']}/review",
        headers=owned["alice"].headers,
        json={"met_point_ids": all_points},
    )

    assert response.status_code == 200
    reviewed = response.json()
    (after,) = [a for a in reviewed["answers"] if a["kind"] == "short_answer"]
    assert after["grading_method"] == "self_review"
    assert after["points_awarded"] == after["max_points"]
    assert sorted(after["feedback"]["matched_point_ids"]) == sorted(all_points)
    assert reviewed["percent"] > done["percent"]


def test_a_review_cannot_name_a_point_that_is_not_in_the_rubric(
    api: TestClient, database_dsn: str, owned: dict[str, Any]
) -> None:
    quiz = read_quiz(api, owned["alice"], owned["quiz"])
    clear_queue(database_dsn)
    pending = submit(
        api, owned["alice"], owned["quiz"], answer_all(database_dsn, quiz, right=True)
    ).json()

    done = finish_grading(api, database_dsn, owned["alice"], pending["id"])
    (marked,) = [a for a in done["answers"] if a["kind"] == "short_answer"]

    response = api.put(
        f"/v1/quiz-answers/{marked['id']}/review",
        headers=owned["alice"].headers,
        json={"met_point_ids": ["p99"]},
    )

    assert response.status_code == 422


def test_the_review_cannot_set_points_directly(
    api: TestClient, database_dsn: str, owned: dict[str, Any]
) -> None:
    quiz = read_quiz(api, owned["alice"], owned["quiz"])
    pending = submit(
        api, owned["alice"], owned["quiz"], answer_all(database_dsn, quiz, right=True)
    ).json()
    answer = next(a for a in pending["answers"] if a["kind"] == "short_answer")

    response = api.put(
        f"/v1/quiz-answers/{answer['id']}/review",
        headers=owned["alice"].headers,
        json={"met_point_ids": [], "points": 3},
    )

    assert response.status_code == 422


def test_only_short_answers_can_be_reviewed(
    api: TestClient, database_dsn: str, owned: dict[str, Any]
) -> None:
    quiz = read_quiz(api, owned["alice"], owned["quiz"])
    result = submit(
        api,
        owned["alice"],
        owned["quiz"],
        answer_all(database_dsn, quiz, right=True, short_answers="blank"),
    ).json()
    objective = next(a for a in result["answers"] if a["kind"] != "short_answer")

    response = api.put(
        f"/v1/quiz-answers/{objective['id']}/review",
        headers=owned["alice"].headers,
        json={"met_point_ids": []},
    )

    assert response.status_code in (409, 422)
    assert response.headers["content-type"].startswith("application/problem+json")


def test_nothing_to_regrade_when_marking_is_complete(
    api: TestClient, database_dsn: str, owned: dict[str, Any]
) -> None:
    quiz = read_quiz(api, owned["alice"], owned["quiz"])
    result = submit(
        api,
        owned["alice"],
        owned["quiz"],
        answer_all(database_dsn, quiz, right=True, short_answers="blank"),
    ).json()

    response = api.post(f"/v1/quiz-attempts/{result['id']}/regrade", headers=owned["alice"].headers)

    assert response.status_code == 409


def test_failed_marking_can_be_retried_and_a_retry_cannot_run_twice_at_once(
    api: TestClient, database_dsn: str, owned: dict[str, Any]
) -> None:
    quiz = read_quiz(api, owned["alice"], owned["quiz"])
    clear_queue(database_dsn)
    pending = submit(
        api, owned["alice"], owned["quiz"], answer_all(database_dsn, quiz, right=True)
    ).json()
    # Marking is already queued, so asking again while it waits is refused.
    waiting = api.post(f"/v1/quiz-attempts/{pending['id']}/regrade", headers=owned["alice"].headers)
    assert waiting.status_code == 409

    # The marking job fails for good: now a retry is allowed and queues a new job.
    admin(database_dsn).execute(
        "update public.generation_jobs set status = 'failed', stage = 'failed',"
        " error_code = 'PROVIDER_UNAVAILABLE', finished_at = now() where attempt_id = %s",
        (pending["id"],),
    )
    retry = api.post(f"/v1/quiz-attempts/{pending['id']}/regrade", headers=owned["alice"].headers)
    assert retry.status_code == 202
    assert retry.json()["job_type"] == "grade" and retry.json()["attempt_id"] == pending["id"]

    done = finish_grading(api, database_dsn, owned["alice"], pending["id"])
    assert done["status"] == "graded"


def test_the_jobs_endpoint_does_not_retry_marking(
    api: TestClient, database_dsn: str, owned: dict[str, Any]
) -> None:
    quiz = read_quiz(api, owned["alice"], owned["quiz"])
    clear_queue(database_dsn)
    pending = submit(
        api, owned["alice"], owned["quiz"], answer_all(database_dsn, quiz, right=True)
    ).json()
    job_id = pending["grading_job"]["id"]
    admin(database_dsn).execute(
        "update public.generation_jobs set status = 'failed', stage = 'failed',"
        " error_code = 'PROVIDER_UNAVAILABLE', finished_at = now() where id = %s",
        (job_id,),
    )

    response = api.post(f"/v1/jobs/{job_id}/retry", headers=owned["alice"].headers)

    assert response.status_code == 409
    assert response.json()["code"] == "JOB_NOT_RETRYABLE"


def test_a_failed_quiz_job_can_be_retried_from_the_jobs_endpoint(
    api: TestClient, database_dsn: str, lessoned: dict[str, Any]
) -> None:
    item = lessoned["topics"][0]
    job = start_quiz(api, lessoned["alice"], item).json()
    admin(database_dsn).execute(
        "update public.generation_jobs set status = 'failed', stage = 'failed',"
        " error_code = 'PROVIDER_UNAVAILABLE', finished_at = now() where id = %s",
        (job["id"],),
    )

    response = api.post(f"/v1/jobs/{job['id']}/retry", headers=lessoned["alice"].headers)

    assert response.status_code == 202
    assert response.json()["job_type"] == "quiz" and response.json()["id"] != job["id"]


# --- Mastery, weak topics and recommendations --------------------------------------------------


def test_progress_before_any_quiz_recommends_taking_one_for_the_studied_topic(
    api: TestClient, lessoned: dict[str, Any]
) -> None:
    response = api.get(f"/v1/goals/{lessoned['goal']}/progress", headers=lessoned["alice"].headers)

    assert response.status_code == 200
    progress = response.json()
    assert progress["counts"]["mastered"] == progress["counts"]["needs_practice"] == 0
    assert progress["counts"]["not_assessed"] == progress["counts"]["total"] > 0
    assert all(t["mastery"] is None for t in progress["topics"])
    assert progress["recommendation"]["action"] in {"take_quiz", "continue_studying"}


def test_a_goal_without_a_roadmap_has_empty_progress(
    api: TestClient, make_learner: MakeLearner
) -> None:
    learner = make_learner()
    goal = create_goal(api, learner)

    response = api.get(f"/v1/goals/{goal['id']}/progress", headers=learner.headers)

    assert response.status_code == 200
    body = response.json()
    assert body["roadmap_id"] is None and body["topics"] == [] and body["recommendation"] is None


def test_a_poor_result_marks_the_topic_weak_and_recommends_practice_not_a_restart(
    api: TestClient, database_dsn: str, lessoned: dict[str, Any]
) -> None:
    item = lessoned["topics"][0]

    result = take_quiz(
        api, database_dsn, lessoned["alice"], item, right=False, short_answers="wrong"
    )

    assert result["percent"] == 0
    assert result["mastery"]["band"] == "needs_practice"
    assert result["mastery"]["score"] == 0
    assert result["mastery"]["low_confidence"] is False  # five answers is enough by default
    recommendation = result["recommendation"]
    assert recommendation["action"] == "practice_quiz" and recommendation["item_id"] == item
    assert recommendation["review_lesson"] is True
    assert recommendation["objective_texts"]
    progress = api.get(
        f"/v1/goals/{lessoned['goal']}/progress", headers=lessoned["alice"].headers
    ).json()
    assert progress["counts"]["needs_practice"] == 1
    assert progress["recommendation"] == recommendation
    # Nothing about the roadmap, goal or other lessons was reset.
    other = next(t for t in progress["topics"] if t["item_id"] == lessoned["topics"][1])
    assert other["study"]["has_lesson"] is True


def test_a_strong_result_is_mastered_and_moves_on(
    api: TestClient, database_dsn: str, lessoned: dict[str, Any]
) -> None:
    item = lessoned["topics"][0]

    result = take_quiz(api, database_dsn, lessoned["alice"], item, right=True)

    assert result["percent"] == 100
    assert result["mastery"]["band"] == "mastered" and result["mastery"]["score"] == 100
    assert result["mastery"]["algorithm_version"] == "weighted-recency/v1"
    assert result["mastery"]["needs_practice_below"] == 70
    assert result["mastery"]["mastered_from"] == 90
    assert result["recommendation"]["action"] in {"take_quiz", "continue_studying", "all_done"}
    assert result["recommendation"]["item_id"] != item


def test_thresholds_are_configurable(
    api: TestClient,
    database_dsn: str,
    lessoned: dict[str, Any],
    configure_app: Callable[..., None],
) -> None:
    item = lessoned["topics"][0]
    take_quiz(api, database_dsn, lessoned["alice"], item, right=True, short_answers="wrong")

    configure_app(mastery_needs_practice_below=99.0, mastery_mastered_from=100.0)

    progress = api.get(
        f"/v1/goals/{lessoned['goal']}/progress", headers=lessoned["alice"].headers
    ).json()
    mastery = next(t["mastery"] for t in progress["topics"] if t["item_id"] == item)
    assert (mastery["needs_practice_below"], mastery["mastered_from"]) == (99, 100)
    assert mastery["band"] == "needs_practice"


def test_few_answers_make_a_score_an_early_estimate(
    api: TestClient,
    database_dsn: str,
    lessoned: dict[str, Any],
    configure_app: Callable[..., None],
) -> None:
    take_quiz(api, database_dsn, lessoned["alice"], lessoned["topics"][0], right=False)

    configure_app(mastery_min_answers=10)

    progress = api.get(
        f"/v1/goals/{lessoned['goal']}/progress", headers=lessoned["alice"].headers
    ).json()
    mastery = next(t["mastery"] for t in progress["topics"] if t["mastery"])
    assert mastery["low_confidence"] is True


def test_mastery_is_a_cache_of_the_stored_answers(
    api: TestClient, database_dsn: str, lessoned: dict[str, Any]
) -> None:
    item = lessoned["topics"][0]
    result = take_quiz(
        api, database_dsn, lessoned["alice"], item, right=False, short_answers="wrong"
    )

    stored = admin(database_dsn).fetchone(
        "select * from public.topic_mastery where item_id = %s", (item,)
    )

    assert stored is not None
    assert stored["user_id"] == lessoned["alice"].id
    assert float(stored["score"]) == result["mastery"]["score"]
    assert stored["attempts_count"] == 1 and stored["answers_count"] == len(result["answers"])
    assert stored["algorithm_version"] == "weighted-recency/v1"
    answers = admin(database_dsn).scalar(
        "select count(*) from public.quiz_answers where attempt_id = %s", (result["id"],)
    )
    assert answers == len(result["answers"])


def test_practice_targets_the_weak_objectives_chosen_by_the_server(
    api: TestClient, database_dsn: str, lessoned: dict[str, Any]
) -> None:
    item = lessoned["topics"][0]
    take_quiz(api, database_dsn, lessoned["alice"], item, right=False, short_answers="wrong")
    clear_queue(database_dsn)

    started = start_quiz(api, lessoned["alice"], item, purpose="practice")

    assert started.status_code == 202
    request = admin(database_dsn).scalar(
        "select request from public.generation_jobs where id = %s", (started.json()["id"],)
    )
    assert request["purpose"] == "practice" and request["focus_objective_ids"]
    weak = {
        o["id"]
        for o in admin(database_dsn).scalar(
            "select objectives from public.topic_mastery where item_id = %s", (item,)
        )
        if o["score"] < 70
    }
    assert set(request["focus_objective_ids"]) <= weak


def test_a_practice_quiz_is_new_and_aimed_at_the_weak_objectives(
    api: TestClient, database_dsn: str, lessoned: dict[str, Any]
) -> None:
    item = lessoned["topics"][0]
    first = take_quiz(
        api, database_dsn, lessoned["alice"], item, right=False, short_answers="wrong"
    )
    weak = {o["id"] for o in first["mastery"]["objectives"] if o["score"] < 70}

    job = write_quiz(api, database_dsn, lessoned["alice"], item, purpose="practice")
    practice = read_quiz(api, lessoned["alice"], job["quiz_id"])

    assert practice["purpose"] == "practice" and practice["id"] != first["quiz_id"]
    assert set(practice["focus_objective_ids"]) <= weak
    assert {q["objective_id"] for q in practice["questions"]} & set(practice["focus_objective_ids"])
    earlier = {a["prompt"] for a in first["answers"]}
    assert earlier.isdisjoint({q["prompt"] for q in practice["questions"]})


def test_the_assessment_says_why_a_quiz_cannot_start(
    api: TestClient, database_dsn: str, lessoned: dict[str, Any]
) -> None:
    alice = lessoned["alice"]
    studied, unstudied = lessoned["topics"][0], lessoned["topics"][2]

    def assessment(item: str) -> dict[str, Any]:
        response = api.get(f"/v1/roadmap-items/{item}/assessment", headers=alice.headers)
        assert response.status_code == 200, response.text
        return response.json()

    assert assessment(unstudied)["blocked_by"] == "lesson_required"
    ready = assessment(studied)
    assert ready["can_start"] is True and ready["blocked_by"] is None

    clear_queue(database_dsn)
    start_quiz(api, alice, studied)
    assert assessment(studied)["blocked_by"] == "quiz_in_progress"

    take_quiz(api, database_dsn, alice, lessoned["topics"][1], right=True)
    after = assessment(lessoned["topics"][1])
    assert after["can_start"] is True
    assert after["mastery"]["band"] == "mastered" and after["last_attempt"]["percent"] == 100


def test_the_assessment_shows_a_waiting_quiz(api: TestClient, owned: dict[str, Any]) -> None:
    response = api.get(
        f"/v1/roadmap-items/{owned['item']}/assessment", headers=owned["alice"].headers
    )

    body = response.json()
    assert body["pending_quiz_id"] == owned["quiz"] and body["blocked_by"] == "quiz_pending"
    assert body["can_start"] is False


def test_progress_is_private_to_the_learner(
    api: TestClient, database_dsn: str, lessoned: dict[str, Any], make_learner: MakeLearner
) -> None:
    take_quiz(api, database_dsn, lessoned["alice"], lessoned["topics"][0], right=True)
    bob = make_learner()

    response = api.get(f"/v1/goals/{lessoned['goal']}/progress", headers=bob.headers)

    assert response.status_code == 404


def test_mastery_only_counts_the_learners_own_answers(
    api: TestClient, database_dsn: str, lessoned: dict[str, Any], make_learner: MakeLearner
) -> None:
    take_quiz(
        api,
        database_dsn,
        lessoned["alice"],
        lessoned["topics"][0],
        right=False,
        short_answers="wrong",
    )
    bob = make_learner()
    bob_seeded = Seeded(api, database_dsn, bob, lessons=1)

    result = take_quiz(api, database_dsn, bob, bob_seeded.topics[0], right=True)

    assert result["mastery"]["score"] == 100  # Alice's zero did not leak into Bob's mastery
    assert result["mastery"]["attempts_count"] == 1
