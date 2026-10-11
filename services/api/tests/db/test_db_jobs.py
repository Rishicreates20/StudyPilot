"""The job queue table in the database: ownership, cancel, constraints and cleanup."""

import uuid
from typing import LiteralString, cast

import psycopg.errors
import pytest

from support.database import admin, create_auth_user
from support.rows import add_goal, add_job

INSERT_JOB = (
    "insert into public.generation_jobs (user_id, goal_id, job_type, idempotency_key, request)"
    " values (%s, %s, 'roadmap', %s, %s) returning *"
)


def job_row(dsn: str, job_id: uuid.UUID) -> dict[str, object]:
    row = admin(dsn).fetchone("select * from public.generation_jobs where id = %s", (job_id,))
    assert row is not None
    return dict(row)


# --- Creating jobs ---------------------------------------------------------------------------


def test_a_learner_can_queue_a_job_for_their_own_goal(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)
    goal_id = add_goal(database_dsn, alice)

    with admin(database_dsn).acting_as("authenticated", alice) as connection:
        row = connection.execute(
            INSERT_JOB, (alice, goal_id, "key-12345678", '{"feedback": "shorter"}')
        ).fetchone()

    assert row is not None
    assert row["status"] == "queued"
    assert row["stage"] == "queued"
    assert row["progress"] == 0
    assert row["attempts"] == 0
    assert row["request"] == {"feedback": "shorter"}
    assert row["locked_by"] is None and row["finished_at"] is None


def test_a_learner_cannot_queue_a_job_for_someone_elses_goal(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)
    bob = create_auth_user(database_dsn)
    goal_id = add_goal(database_dsn, alice)

    with admin(database_dsn).acting_as("authenticated", bob) as connection:
        # Bob names his own user id, so row security passes; the composite key
        # (goal_id, user_id) does not exist, so the database refuses the job.
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            connection.execute(INSERT_JOB, (bob, goal_id, None, "{}"))


def test_a_learner_cannot_queue_a_job_in_someone_elses_name(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)
    bob = create_auth_user(database_dsn)
    goal_id = add_goal(database_dsn, alice)

    with admin(database_dsn).acting_as("authenticated", bob) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(INSERT_JOB, (alice, goal_id, None, "{}"))


@pytest.mark.parametrize(
    "column",
    [
        "status",
        "stage",
        "progress",
        "attempts",
        "max_attempts",
        "run_at",
        "locked_by",
        "locked_until",
        "cancel_requested",
        "checkpoint",
        "error_code",
        "error_message",
        "finished_at",
        "created_at",
    ],
)
def test_a_learner_cannot_set_the_systems_columns_when_creating_a_job(
    database_dsn: str, column: str
) -> None:
    alice = create_auth_user(database_dsn)
    goal_id = add_goal(database_dsn, alice)

    with admin(database_dsn).acting_as("authenticated", alice) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                cast(
                    LiteralString,
                    f"insert into public.generation_jobs (user_id, goal_id, job_type, {column})"  # noqa: S608
                    f" values (%s, %s, 'roadmap', null)",
                ),
                (alice, goal_id),
            )


def test_only_known_job_types_are_accepted(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)
    goal_id = add_goal(database_dsn, alice)

    with pytest.raises(psycopg.errors.CheckViolation):
        admin(database_dsn).execute(
            "insert into public.generation_jobs (user_id, goal_id, job_type)"
            " values (%s, %s, 'quiz')",
            (alice, goal_id),
        )


# --- One at a time, and idempotency ----------------------------------------------------------


def test_a_goal_cannot_have_two_unfinished_jobs(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)
    goal_id = add_goal(database_dsn, alice)
    add_job(database_dsn, alice, goal_id)

    with pytest.raises(psycopg.errors.UniqueViolation):
        add_job(database_dsn, alice, goal_id)
    with pytest.raises(psycopg.errors.UniqueViolation):
        add_job(database_dsn, alice, goal_id, status="running")


def test_a_new_job_is_allowed_once_the_previous_one_has_finished(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)
    goal_id = add_goal(database_dsn, alice)
    for finished in ("completed", "failed", "cancelled"):
        add_job(database_dsn, alice, goal_id, status=finished)

    queued = add_job(database_dsn, alice, goal_id)

    assert job_row(database_dsn, queued)["status"] == "queued"


def test_different_goals_can_generate_at_the_same_time(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)

    add_job(database_dsn, alice, add_goal(database_dsn, alice))
    add_job(database_dsn, alice, add_goal(database_dsn, alice))


def test_an_idempotency_key_is_used_once_per_learner(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)
    bob = create_auth_user(database_dsn)
    alice_goal = add_goal(database_dsn, alice)
    bob_goal = add_goal(database_dsn, bob)
    add_job(database_dsn, alice, alice_goal, status="completed", idempotency_key="shared-key-1")

    with pytest.raises(psycopg.errors.UniqueViolation):
        add_job(database_dsn, alice, alice_goal, idempotency_key="shared-key-1")
    add_job(database_dsn, bob, bob_goal, idempotency_key="shared-key-1")  # another learner: fine


# --- Reading ---------------------------------------------------------------------------------


def test_a_learner_sees_only_their_own_jobs(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)
    bob = create_auth_user(database_dsn)
    mine = add_job(database_dsn, alice, add_goal(database_dsn, alice))
    add_job(database_dsn, bob, add_goal(database_dsn, bob))

    with admin(database_dsn).acting_as("authenticated", alice) as connection:
        ids = [row["id"] for row in connection.execute("select id from public.generation_jobs")]

    assert mine in ids
    assert all(job_row(database_dsn, i)["user_id"] == alice for i in ids)


def test_anonymous_visitors_have_no_access_to_jobs(database_dsn: str) -> None:
    with admin(database_dsn).acting_as("anon") as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("select * from public.generation_jobs")


# --- Cancelling ------------------------------------------------------------------------------


def test_cancelling_a_queued_job_takes_effect_immediately(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)
    job_id = add_job(database_dsn, alice, add_goal(database_dsn, alice))

    with admin(database_dsn).acting_as("authenticated", alice) as connection:
        row = connection.execute(
            "update public.generation_jobs set cancel_requested = true where id = %s returning *",
            (job_id,),
        ).fetchone()

    assert row is not None
    assert row["status"] == "cancelled"
    assert row["stage"] == "cancelled"
    assert row["finished_at"] is not None


def test_cancelling_a_running_job_only_raises_the_flag(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)
    job_id = add_job(database_dsn, alice, add_goal(database_dsn, alice), status="running")

    with admin(database_dsn).acting_as("authenticated", alice) as connection:
        row = connection.execute(
            "update public.generation_jobs set cancel_requested = true where id = %s returning *",
            (job_id,),
        ).fetchone()

    assert row is not None
    assert row["status"] == "running"  # the worker stops it at the next stage boundary
    assert row["cancel_requested"] is True
    assert row["finished_at"] is None


def test_a_finished_job_cannot_be_touched(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)
    job_id = add_job(database_dsn, alice, add_goal(database_dsn, alice), status="completed")

    with admin(database_dsn).acting_as("authenticated", alice) as connection:
        result = connection.execute(
            "update public.generation_jobs set cancel_requested = true where id = %s", (job_id,)
        )
        assert result.rowcount == 0


def test_another_learner_cannot_cancel_the_job(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)
    bob = create_auth_user(database_dsn)
    job_id = add_job(database_dsn, alice, add_goal(database_dsn, alice))

    with admin(database_dsn).acting_as("authenticated", bob) as connection:
        result = connection.execute(
            "update public.generation_jobs set cancel_requested = true where id = %s", (job_id,)
        )
        assert result.rowcount == 0

    assert job_row(database_dsn, job_id)["status"] == "queued"


def test_a_cancel_request_cannot_be_withdrawn(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)
    job_id = add_job(
        database_dsn, alice, add_goal(database_dsn, alice), status="running", cancel_requested=True
    )

    with admin(database_dsn).acting_as("authenticated", alice) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "update public.generation_jobs set cancel_requested = false where id = %s",
                (job_id,),
            )


@pytest.mark.parametrize(
    "assignment",
    [
        "status = 'completed'",
        "status = 'queued'",
        "attempts = 0",
        "progress = 100",
        "error_code = 'X'",
        "locked_by = null",
        "goal_id = gen_random_uuid()",
        "user_id = gen_random_uuid()",
    ],
)
def test_a_learner_cannot_change_anything_but_the_cancel_flag(
    database_dsn: str, assignment: str
) -> None:
    alice = create_auth_user(database_dsn)
    job_id = add_job(database_dsn, alice, add_goal(database_dsn, alice), status="running")

    with admin(database_dsn).acting_as("authenticated", alice) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                cast(
                    LiteralString,
                    f"update public.generation_jobs set {assignment} where id = %s",  # noqa: S608
                ),
                (job_id,),
            )


def test_a_learner_cannot_delete_jobs(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)
    job_id = add_job(database_dsn, alice, add_goal(database_dsn, alice), status="completed")

    with admin(database_dsn).acting_as("authenticated", alice) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("delete from public.generation_jobs where id = %s", (job_id,))


# --- Consistency rules -----------------------------------------------------------------------


def test_a_running_job_must_be_locked(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)
    job_id = add_job(database_dsn, alice, add_goal(database_dsn, alice))

    with pytest.raises(psycopg.errors.CheckViolation):
        admin(database_dsn).execute(
            "update public.generation_jobs set status = 'running' where id = %s", (job_id,)
        )


def test_a_lock_needs_both_its_owner_and_its_expiry(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)
    job_id = add_job(database_dsn, alice, add_goal(database_dsn, alice))

    with pytest.raises(psycopg.errors.CheckViolation):
        admin(database_dsn).execute(
            "update public.generation_jobs set locked_until = now() where id = %s", (job_id,)
        )


def test_a_finished_job_needs_a_finish_time_and_an_unfinished_one_must_not_have_one(
    database_dsn: str,
) -> None:
    alice = create_auth_user(database_dsn)
    job_id = add_job(database_dsn, alice, add_goal(database_dsn, alice))

    with pytest.raises(psycopg.errors.CheckViolation):
        admin(database_dsn).execute(
            "update public.generation_jobs set status = 'completed' where id = %s", (job_id,)
        )
    with pytest.raises(psycopg.errors.CheckViolation):
        admin(database_dsn).execute(
            "update public.generation_jobs set finished_at = now() where id = %s", (job_id,)
        )


def test_a_failed_job_must_say_why(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)
    job_id = add_job(database_dsn, alice, add_goal(database_dsn, alice))

    with pytest.raises(psycopg.errors.CheckViolation):
        admin(database_dsn).execute(
            "update public.generation_jobs set status = 'failed', finished_at = now()"
            " where id = %s",
            (job_id,),
        )


@pytest.mark.parametrize(
    "assignment",
    ["progress = 101", "progress = -1", "attempts = -1", "max_attempts = 0", "stage = ''"],
)
def test_numeric_and_text_columns_are_range_checked(database_dsn: str, assignment: str) -> None:
    alice = create_auth_user(database_dsn)
    job_id = add_job(database_dsn, alice, add_goal(database_dsn, alice))

    with pytest.raises(psycopg.errors.CheckViolation):
        admin(database_dsn).execute(
            cast(LiteralString, f"update public.generation_jobs set {assignment} where id = %s"),  # noqa: S608
            (job_id,),
        )


def test_updates_move_the_updated_at_timestamp(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)
    job_id = add_job(database_dsn, alice, add_goal(database_dsn, alice))
    before = job_row(database_dsn, job_id)["updated_at"]

    admin(database_dsn).execute(
        "update public.generation_jobs set progress = 10 where id = %s", (job_id,)
    )

    assert job_row(database_dsn, job_id)["updated_at"] > before  # type: ignore[operator]


# --- Cleanup and the usage ledger ------------------------------------------------------------


def test_deleting_a_goal_removes_its_jobs_and_usage(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)
    goal_id = add_goal(database_dsn, alice, status="archived")
    job_id = add_job(database_dsn, alice, goal_id, status="completed")
    admin(database_dsn).execute(
        "insert into public.ai_usage_events (user_id, job_id, purpose, provider, prompt_version)"
        " values (%s, %s, 'roadmap.plan', 'fake', 'test/v1')",
        (alice, job_id),
    )

    admin(database_dsn).execute("delete from public.learning_goals where id = %s", (goal_id,))

    assert (
        admin(database_dsn).scalar(
            "select count(*) from public.generation_jobs where id = %s", (job_id,)
        )
        == 0
    )
    assert (
        admin(database_dsn).scalar(
            "select count(*) from public.ai_usage_events where job_id = %s", (job_id,)
        )
        == 0
    )


def test_usage_events_are_readable_by_their_owner_but_not_writable(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)
    bob = create_auth_user(database_dsn)
    job_id = add_job(database_dsn, alice, add_goal(database_dsn, alice), status="completed")
    admin(database_dsn).execute(
        "insert into public.ai_usage_events (user_id, job_id, purpose, provider, prompt_version)"
        " values (%s, %s, 'roadmap.plan', 'fake', 'test/v1')",
        (alice, job_id),
    )

    with admin(database_dsn).acting_as("authenticated", alice) as connection:
        assert len(connection.execute("select * from public.ai_usage_events").fetchall()) == 1
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "insert into public.ai_usage_events (user_id, job_id, purpose, provider,"
                " prompt_version) values (%s, %s, 'x', 'fake', 'v')",
                (alice, job_id),
            )
    with admin(database_dsn).acting_as("authenticated", bob) as connection:
        assert connection.execute("select * from public.ai_usage_events").fetchall() == []


def test_usage_for_someone_elses_job_is_refused(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)
    bob = create_auth_user(database_dsn)
    job_id = add_job(database_dsn, alice, add_goal(database_dsn, alice))

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        admin(database_dsn).execute(
            "insert into public.ai_usage_events (user_id, job_id, purpose, provider,"
            " prompt_version) values (%s, %s, 'x', 'fake', 'v')",
            (bob, job_id),
        )
