"""The worker writing quizzes for real: queue -> writer -> validation -> PostgreSQL."""

import uuid
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from psycopg.types.json import Jsonb

from app.ai.factory import builtin_responder
from app.ai.fake import FakeProvider
from app.ai.fake_quiz import sample_quiz
from app.ai.provider import LLMAuthError, LLMRateLimited, StructuredRequest
from app.ai.quiz.schema import DraftQuiz
from app.core.db import Database
from app.jobs import queue, quiz_store
from app.jobs.errors import JobCancelled, LeaseLost
from app.jobs.worker import Worker
from support.database import admin
from support.lessons import Seeded, seed_learning_state
from support.quizzes import changed_quiz, valid_quiz
from support.rows import add_job, add_lesson
from support.worker import job_state, make_env, worker_settings

pytestmark = pytest.mark.anyio


def worker_for(database: Database, dsn: str, provider: Any, **settings: Any) -> Worker:
    return Worker(make_env(database, worker_settings(dsn, **settings), provider))


def quizzes_of(dsn: str, item: uuid.UUID) -> list[dict[str, Any]]:
    rows = admin(dsn).fetchall(
        "select * from public.quizzes where item_id = %s order by created_at", (item,)
    )
    return [dict(row) for row in rows]


def questions_of(dsn: str, quiz: uuid.UUID) -> list[dict[str, Any]]:
    rows = admin(dsn).fetchall(
        "select * from public.questions where quiz_id = %s order by position", (quiz,)
    )
    return [dict(row) for row in rows]


def keys_of(dsn: str, quiz: uuid.UUID) -> list[dict[str, Any]]:
    rows = admin(dsn).fetchall(
        "select k.* from public.question_answer_keys k join public.questions q"
        " on q.id = k.question_id where q.quiz_id = %s order by q.position",
        (quiz,),
    )
    return [dict(row) for row in rows]


def usage_of(dsn: str, job: uuid.UUID) -> list[str]:
    rows = admin(dsn).fetchall(
        "select purpose from public.ai_usage_events where job_id = %s order by created_at", (job,)
    )
    return [row["purpose"] for row in rows]


def seed_quiz_job(
    dsn: str, *, request: dict[str, Any] | None = None, topic: int = 0, **goal_fields: Any
) -> tuple[Seeded, uuid.UUID, uuid.UUID, uuid.UUID]:
    """A learner with a roadmap, a lesson and a queued quiz job: (seeded, item, lesson, job)."""
    seeded = seed_learning_state(dsn, **goal_fields)
    item = seeded.topics[topic]
    lesson_job = add_job(
        dsn, seeded.user, seeded.goal, status="completed", job_type="lesson", item_id=item
    )
    lesson = add_lesson(dsn, seeded.user, seeded.roadmap, item, lesson_job)
    body: dict[str, Any] = {"purpose": "check", "lesson_id": str(lesson), **(request or {})}
    job = add_job(dsn, seeded.user, seeded.goal, job_type="quiz", item_id=item, request=Jsonb(body))
    return seeded, item, lesson, job


def broken(request: StructuredRequest) -> DraftQuiz:
    """A draft that asks the same question twice (a duplicate the checks refuse)."""

    def edit(data: dict[str, Any]) -> None:
        data["questions"][1]["prompt"] = data["questions"][0]["prompt"]

    return changed_quiz(sample_quiz(request.input_data), edit)


# --- The happy path --------------------------------------------------------------------------


async def test_a_queued_job_becomes_a_stored_quiz_with_secret_keys(
    database: Database, database_dsn: str
) -> None:
    seeded, item, lesson, job = seed_quiz_job(database_dsn)
    worker = worker_for(database, database_dsn, FakeProvider(builtin_responder))

    assert await worker.run_once() is True

    state = job_state(database_dsn, job)
    assert (state["status"], state["stage"], state["progress"]) == ("completed", "done", 100)
    assert state["attempts"] == 1 and state["error_code"] is None and state["locked_by"] is None
    (quiz,) = quizzes_of(database_dsn, item)
    assert quiz["user_id"] == seeded.user and quiz["roadmap_id"] == seeded.roadmap
    assert quiz["job_id"] == job and quiz["lesson_id"] == lesson
    assert (quiz["purpose"], quiz["language"], quiz["question_count"]) == ("check", "en", 5)
    assert quiz["is_synthetic"] is True and quiz["provider"] == "fake"
    assert quiz["prompt_version"] == "quiz-writer/v1"
    questions = questions_of(database_dsn, quiz["id"])
    keys = keys_of(database_dsn, quiz["id"])
    assert [q["position"] for q in questions] == [1, 2, 3, 4, 5]
    assert {k["question_id"] for k in keys} == {q["id"] for q in questions}
    assert all(k["user_id"] == seeded.user and k["explanation"] for k in keys)
    for question, key in zip(questions, keys, strict=True):
        if question["kind"] == "short_answer":
            assert question["options"] is None
            assert (
                key["correct_option_id"] is None and key["rubric"]["points"] and key["model_answer"]
            )
        else:
            assert key["correct_option_id"] in {o["id"] for o in question["options"]}
            assert key["rubric"] is None


async def test_the_stored_questions_carry_no_trace_of_the_answer(
    database: Database, database_dsn: str
) -> None:
    _, item, _, _ = seed_quiz_job(database_dsn)

    await worker_for(database, database_dsn, FakeProvider(builtin_responder)).run_once()

    (quiz,) = quizzes_of(database_dsn, item)
    for question in questions_of(database_dsn, quiz["id"]):
        assert set(question) == {
            "id", "user_id", "quiz_id", "position", "kind", "prompt", "options", "objective_id",
            "difficulty", "max_points",
        }  # fmt: skip
        options: list[dict[str, Any]] = question["options"] or []
        assert all(set(option) == {"id", "text"} for option in options)


async def test_every_model_call_is_recorded_in_the_usage_ledger(
    database: Database, database_dsn: str
) -> None:
    _, _, _, job = seed_quiz_job(database_dsn)

    await worker_for(database, database_dsn, FakeProvider(builtin_responder)).run_once()

    assert usage_of(database_dsn, job) == ["quiz.write"]


async def test_the_model_is_told_the_topic_the_lesson_and_the_objectives(
    database: Database, database_dsn: str
) -> None:
    _, _, _, _ = seed_quiz_job(database_dsn)
    provider = FakeProvider(builtin_responder)

    await worker_for(database, database_dsn, provider).run_once()

    sent = provider.requests[0].input_data
    assert sent["topic"]["title"] == "Topic 1" and sent["purpose"] == "check"
    assert sent["lesson"]["sections"] and sent["objectives"]
    assert sent["quiz"] == {"question_count": 5, "max_short_answers": 1}
    assert provider.requests[0].user.count("<learner_data>") <= 1


async def test_one_worker_runs_every_kind_of_job(database: Database, database_dsn: str) -> None:
    _, _, _, quiz_job = seed_quiz_job(database_dsn)
    worker = worker_for(database, database_dsn, FakeProvider(builtin_responder))

    assert await worker.run_once() is True
    assert await worker.run_once() is False  # nothing else was queued

    assert job_state(database_dsn, quiz_job)["status"] == "completed"


async def test_a_second_quiz_is_told_what_was_already_asked(
    database: Database, database_dsn: str
) -> None:
    seeded, item, lesson, _ = seed_quiz_job(database_dsn)
    provider = FakeProvider(builtin_responder)
    worker = worker_for(database, database_dsn, provider)
    await worker.run_once()
    (first,) = quizzes_of(database_dsn, item)
    asked = [q["prompt"] for q in questions_of(database_dsn, first["id"])]
    # The first quiz is taken; practising again queues a new job.
    admin(database_dsn).execute(
        "insert into public.quiz_attempts (user_id, quiz_id, status) values (%s, %s, 'grading')",
        (seeded.user, first["id"]),
    )
    add_job(
        database_dsn, seeded.user, seeded.goal, job_type="quiz", item_id=item,
        request=Jsonb({"purpose": "practice", "lesson_id": str(lesson)}),
    )  # fmt: skip

    await worker.run_once()

    assert provider.requests[1].input_data["do_not_repeat"] == asked
    second = [q for q in quizzes_of(database_dsn, item) if q["id"] != first["id"]]
    assert len(second) == 1 and second[0]["purpose"] == "practice"
    new_prompts = {q["prompt"] for q in questions_of(database_dsn, second[0]["id"])}
    assert new_prompts.isdisjoint(asked)


# --- A request is only a hint -----------------------------------------------------------------


async def test_the_question_count_is_clamped_to_what_the_product_allows(
    database: Database, database_dsn: str
) -> None:
    _, item, _, _ = seed_quiz_job(database_dsn, request={"question_count": 1000})
    provider = FakeProvider(builtin_responder)

    await worker_for(database, database_dsn, provider).run_once()

    assert provider.requests[0].input_data["quiz"]["question_count"] == 10
    (quiz,) = quizzes_of(database_dsn, item)
    assert quiz["question_count"] == 10


NONSENSE_REQUESTS: list[dict[str, Any]] = [
    {"question_count": "many"},
    {"question_count": True},
    {"question_count": None},
    {"max_short_answers": -4},
    {"purpose": "exam"},
    {"focus_objective_ids": "o1"},
    {"focus_objective_ids": [1, None, {}]},
    {"extra": "ignored"},
]


@pytest.mark.parametrize("request_body", NONSENSE_REQUESTS)
async def test_nonsense_in_a_jobs_request_is_ignored(
    database: Database, database_dsn: str, request_body: dict[str, Any]
) -> None:
    _, item, _, job = seed_quiz_job(database_dsn, request=request_body)
    provider = FakeProvider(builtin_responder)

    await worker_for(database, database_dsn, provider).run_once()

    assert job_state(database_dsn, job)["status"] == "completed"
    (quiz,) = quizzes_of(database_dsn, item)
    assert quiz["purpose"] == "check" and quiz["focus_objective_ids"] == []
    assert provider.requests[0].input_data["quiz"]["max_short_answers"] in {0, 1}


async def test_focus_objectives_the_topic_does_not_have_are_dropped(
    database: Database, database_dsn: str
) -> None:
    _, item, _, _ = seed_quiz_job(
        database_dsn,
        request={"purpose": "practice", "focus_objective_ids": ["o1", "o999", "x; drop table"]},
    )
    admin(database_dsn).execute(
        "update public.roadmap_items set objective_ids = '{o1,o2}' where id = %s", (item,)
    )
    provider = FakeProvider(builtin_responder)

    await worker_for(database, database_dsn, provider).run_once()

    assert provider.requests[0].input_data["focus_objective_ids"] == ["o1"]
    (quiz,) = quizzes_of(database_dsn, item)
    assert quiz["focus_objective_ids"] == ["o1"] and quiz["purpose"] == "practice"


async def test_a_job_cannot_borrow_another_learners_lesson(
    database: Database, database_dsn: str
) -> None:
    other = seed_learning_state(database_dsn)
    other_job = add_job(
        database_dsn, other.user, other.goal, status="completed", job_type="lesson",
        item_id=other.topics[0],
    )  # fmt: skip
    stolen = add_lesson(database_dsn, other.user, other.roadmap, other.topics[0], other_job)
    _, item, _, job = seed_quiz_job(database_dsn, request={"lesson_id": str(stolen)})
    provider = FakeProvider()

    await worker_for(database, database_dsn, provider).run_once()

    state = job_state(database_dsn, job)
    assert (state["status"], state["error_code"]) == ("failed", "LESSON_REQUIRED")
    assert provider.requests == [] and quizzes_of(database_dsn, item) == []


async def test_a_job_without_a_lesson_in_its_request_fails_clearly(
    database: Database, database_dsn: str
) -> None:
    seeded = seed_learning_state(database_dsn)
    item = seeded.topics[0]
    lesson_job = add_job(
        database_dsn, seeded.user, seeded.goal, status="completed", job_type="lesson", item_id=item
    )
    add_lesson(database_dsn, seeded.user, seeded.roadmap, item, lesson_job)
    job = add_job(database_dsn, seeded.user, seeded.goal, job_type="quiz", item_id=item)

    await worker_for(database, database_dsn, FakeProvider()).run_once()

    state = job_state(database_dsn, job)
    assert (state["status"], state["error_code"]) == ("failed", "LESSON_REQUIRED")
    assert quizzes_of(database_dsn, item) == []


# --- Invalid output and repair ---------------------------------------------------------------


async def test_a_quiz_that_fails_the_checks_is_repaired_once(
    database: Database, database_dsn: str
) -> None:
    _, item, _, job = seed_quiz_job(database_dsn)

    def fixed(request: StructuredRequest) -> Any:
        return sample_quiz(request.input_data)

    replies: Iterator[Callable[[StructuredRequest], Any]] = iter([broken, fixed])

    def answer(request: StructuredRequest) -> Any:
        return next(replies)(request)

    await worker_for(database, database_dsn, FakeProvider(answer)).run_once()

    assert job_state(database_dsn, job)["status"] == "completed"
    assert usage_of(database_dsn, job) == ["quiz.write", "quiz.repair"]
    assert len(quizzes_of(database_dsn, item)) == 1


async def test_a_quiz_that_fails_twice_ends_the_job_and_stores_nothing(
    database: Database, database_dsn: str
) -> None:
    _, item, _, job = seed_quiz_job(database_dsn)
    provider = FakeProvider(broken)

    await worker_for(database, database_dsn, provider).run_once()

    state = job_state(database_dsn, job)
    assert (state["status"], state["error_code"]) == ("failed", "QUIZ_INVALID")
    assert "quality checks" in state["error_message"]
    assert len(provider.requests) == 2  # one write, one repair, no more
    assert quizzes_of(database_dsn, item) == []
    assert usage_of(database_dsn, job) == ["quiz.write", "quiz.repair"]


async def test_the_failure_message_never_quotes_the_model(
    database: Database, database_dsn: str
) -> None:
    _, _, _, job = seed_quiz_job(database_dsn)

    def leaky(request: StructuredRequest) -> DraftQuiz:
        def edit(data: dict[str, Any]) -> None:
            data["questions"][0]["prompt"] = "SECRET-CANARY-7731 " + data["questions"][0]["prompt"]
            data["questions"][1]["prompt"] = data["questions"][0]["prompt"]

        return changed_quiz(sample_quiz(request.input_data), edit)

    await worker_for(database, database_dsn, FakeProvider(leaky)).run_once()

    state = job_state(database_dsn, job)
    assert "SECRET-CANARY" not in str(state)


# --- Provider trouble ------------------------------------------------------------------------


async def test_a_busy_model_puts_the_job_back_and_the_next_run_succeeds(
    database: Database, database_dsn: str
) -> None:
    _, item, _, job = seed_quiz_job(database_dsn)
    provider = FakeProvider(builtin_responder, script=[LLMRateLimited("busy")])
    worker = worker_for(database, database_dsn, provider)

    await worker.run_once()

    waiting = job_state(database_dsn, job)
    assert (waiting["status"], waiting["stage"], waiting["error_code"]) == (
        "queued",
        "waiting_retry",
        "AI_RATE_LIMITED",
    )
    assert quizzes_of(database_dsn, item) == []

    await worker.run_once()

    done = job_state(database_dsn, job)
    assert (done["status"], done["attempts"], done["error_code"]) == ("completed", 2, None)
    assert len(quizzes_of(database_dsn, item)) == 1


async def test_a_rejected_key_fails_at_once_without_retrying(
    database: Database, database_dsn: str
) -> None:
    _, _, _, job = seed_quiz_job(database_dsn)
    provider = FakeProvider(script=[LLMAuthError("no")])

    await worker_for(database, database_dsn, provider).run_once()

    state = job_state(database_dsn, job)
    assert (state["status"], state["error_code"], state["attempts"]) == (
        "failed",
        "AI_AUTH_FAILED",
        1,
    )


async def test_without_a_provider_the_job_fails_with_a_clear_reason(
    database: Database, database_dsn: str
) -> None:
    _, item, _, job = seed_quiz_job(database_dsn)

    await worker_for(database, database_dsn, None).run_once()

    state = job_state(database_dsn, job)
    assert (state["status"], state["error_code"]) == ("failed", "AI_NOT_CONFIGURED")
    assert quizzes_of(database_dsn, item) == []


async def test_a_validated_quiz_is_not_paid_for_twice(
    database: Database, database_dsn: str
) -> None:
    _, item, _, job = seed_quiz_job(database_dsn)
    checkpoint = quiz_store.checkpoint_of(
        valid_quiz(), quiz_store.QuizMeta("quiz-writer/v1", "fake", "fake-1", synthetic=True)
    )
    admin(database_dsn).execute(
        "update public.generation_jobs set checkpoint = %s where id = %s", (Jsonb(checkpoint), job)
    )
    provider = FakeProvider()  # any call to it fails the test

    await worker_for(database, database_dsn, provider).run_once()

    assert provider.requests == []
    assert job_state(database_dsn, job)["status"] == "completed"
    assert len(quizzes_of(database_dsn, item)) == 1
    assert usage_of(database_dsn, job) == []


# --- Cancelling and changed circumstances -----------------------------------------------------


async def test_a_cancel_that_arrives_while_the_model_is_working_stores_nothing(
    database: Database, database_dsn: str
) -> None:
    _, item, _, job = seed_quiz_job(database_dsn)

    def cancel_then_answer(request: StructuredRequest) -> Any:
        admin(database_dsn).execute(
            "update public.generation_jobs set cancel_requested = true where id = %s", (job,)
        )
        return builtin_responder(request)

    await worker_for(database, database_dsn, FakeProvider(cancel_then_answer)).run_once()

    assert job_state(database_dsn, job)["status"] == "cancelled"
    assert quizzes_of(database_dsn, item) == []


async def test_a_goal_archived_while_the_job_waited_is_reported(
    database: Database, database_dsn: str
) -> None:
    seeded, item, _, job = seed_quiz_job(database_dsn)
    admin(database_dsn).execute(
        "update public.learning_goals set status = 'archived' where id = %s", (seeded.goal,)
    )
    provider = FakeProvider()

    await worker_for(database, database_dsn, provider).run_once()

    state = job_state(database_dsn, job)
    assert (state["status"], state["error_code"]) == ("failed", "GOAL_UNAVAILABLE")
    assert provider.requests == [] and quizzes_of(database_dsn, item) == []


# --- Storing is exactly once ------------------------------------------------------------------


async def _claim(database: Database) -> queue.Job:
    async with database.system_session() as connection:
        claimed = await queue.claim_next(
            connection, worker_id="w1", lease_seconds=60, max_attempts=3
        )
    assert claimed is not None
    return claimed


META = quiz_store.QuizMeta("p", "fake", "m", synthetic=True)


async def save(
    database: Database,
    claimed: queue.Job,
    worker: str,
    seeded: Seeded,
    item: uuid.UUID,
    lesson: uuid.UUID,
) -> quiz_store.SavedQuiz:
    async with database.system_session() as connection:
        return await quiz_store.save_quiz(
            connection, claimed, worker, roadmap_id=seeded.roadmap, item_id=item,
            lesson_id=lesson, quiz=valid_quiz(), meta=META, purpose="check",
            focus_objective_ids=[],
        )  # fmt: skip


async def test_storing_twice_for_one_job_returns_the_same_quiz(
    database: Database, database_dsn: str
) -> None:
    seeded, item, lesson, job = seed_quiz_job(database_dsn)
    claimed = await _claim(database)
    assert claimed.id == job

    first = await save(database, claimed, "w1", seeded, item, lesson)
    # A crash between "stored" and "marked complete" is simulated by repeating the call.
    admin(database_dsn).execute(
        "update public.generation_jobs set status = 'running', locked_by = 'w1',"
        " locked_until = now() + interval '1 minute', finished_at = null where id = %s",
        (job,),
    )
    second = await save(database, claimed, "w1", seeded, item, lesson)

    assert first.id == second.id
    assert len(quizzes_of(database_dsn, item)) == 1
    assert job_state(database_dsn, job)["status"] == "completed"


async def test_a_worker_that_lost_its_lease_cannot_store_a_quiz(
    database: Database, database_dsn: str
) -> None:
    seeded, item, lesson, _ = seed_quiz_job(database_dsn)
    claimed = await _claim(database)

    with pytest.raises(LeaseLost):
        await save(database, claimed, "someone-else", seeded, item, lesson)

    assert quizzes_of(database_dsn, item) == []


async def test_a_cancelled_job_cannot_store_a_quiz(database: Database, database_dsn: str) -> None:
    seeded, item, lesson, job = seed_quiz_job(database_dsn)
    claimed = await _claim(database)
    admin(database_dsn).execute(
        "update public.generation_jobs set cancel_requested = true where id = %s", (job,)
    )

    with pytest.raises(JobCancelled):
        await save(database, claimed, "w1", seeded, item, lesson)

    assert quizzes_of(database_dsn, item) == []


async def test_a_quiz_that_fails_to_store_leaves_no_half_written_rows(
    database: Database, database_dsn: str
) -> None:
    seeded, item, _, _ = seed_quiz_job(database_dsn)
    claimed = await _claim(database)
    # A lesson that belongs to nobody breaks the quiz insert after the job lock is taken.
    with pytest.raises(Exception):  # noqa: B017 - any database error will do
        await save(database, claimed, "w1", seeded, item, uuid.uuid4())

    assert quizzes_of(database_dsn, item) == []
    leftovers = admin(database_dsn).scalar(
        "select count(*) from public.questions where user_id = %s", (seeded.user,)
    )
    assert leftovers == 0
    assert (
        job_state(database_dsn, claimed.id)["status"] == "running"
    )  # still the worker's to settle
