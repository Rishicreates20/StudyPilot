"""Lessons and study progress in the database: who can write what, and what is always true."""

import uuid
from typing import Any, LiteralString

import psycopg.errors
import pytest
from psycopg import sql
from psycopg.types.json import Jsonb

from support.database import admin, create_auth_user
from support.lessons import Seeded, add_lesson_job, seed_learning_state
from support.rows import add_goal, add_job, add_lesson, add_roadmap

INSERT_LESSON_JOB = (
    "insert into public.generation_jobs (user_id, goal_id, item_id, job_type)"
    " values (%s, %s, %s, 'lesson') returning *"
)
CONSTRAINT_VIOLATIONS = (psycopg.errors.CheckViolation, psycopg.errors.ForeignKeyViolation)


def queue_as_learner(dsn: str, who: uuid.UUID, goal: uuid.UUID, item: uuid.UUID | None) -> None:
    with admin(dsn).acting_as("authenticated", who) as connection:
        connection.execute(INSERT_LESSON_JOB, (who, goal, item))


@pytest.fixture
def seeded(database_dsn: str) -> Seeded:
    return seed_learning_state(database_dsn)


def lesson_for(dsn: str, seeded: Seeded, item: uuid.UUID, **fields: Any) -> uuid.UUID:
    job = add_lesson_job(dsn, seeded, item, status="completed")
    return add_lesson(dsn, seeded.user, seeded.roadmap, item, job, **fields)


# --- Queuing a lesson job ---------------------------------------------------------------------


def test_a_learner_can_queue_a_lesson_for_a_topic_of_their_current_roadmap(
    database_dsn: str, seeded: Seeded
) -> None:
    with admin(database_dsn).acting_as("authenticated", seeded.user) as connection:
        row = connection.execute(
            INSERT_LESSON_JOB, (seeded.user, seeded.goal, seeded.topics[0])
        ).fetchone()

    assert row is not None
    assert (row["job_type"], row["status"], row["item_id"]) == (
        "lesson",
        "queued",
        seeded.topics[0],
    )


def test_an_optional_extra_can_have_a_lesson_too(database_dsn: str, seeded: Seeded) -> None:
    queue_as_learner(database_dsn, seeded.user, seeded.goal, seeded.extra)


def test_a_revision_session_cannot_have_a_lesson(database_dsn: str, seeded: Seeded) -> None:
    with pytest.raises(psycopg.errors.CheckViolation, match="current roadmap"):
        queue_as_learner(database_dsn, seeded.user, seeded.goal, seeded.revision)


def test_a_lesson_job_must_name_a_topic(database_dsn: str, seeded: Seeded) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        queue_as_learner(database_dsn, seeded.user, seeded.goal, None)


def test_a_roadmap_job_cannot_name_a_topic(database_dsn: str, seeded: Seeded) -> None:
    with admin(database_dsn).acting_as("authenticated", seeded.user) as connection:
        with pytest.raises(psycopg.errors.CheckViolation, match="item_matches_type"):
            connection.execute(
                "insert into public.generation_jobs (user_id, goal_id, item_id, job_type)"
                " values (%s, %s, %s, 'roadmap')",
                (seeded.user, seeded.goal, seeded.topics[0]),
            )


def test_a_topic_cannot_be_paired_with_a_different_goal_of_the_same_learner(
    database_dsn: str, seeded: Seeded
) -> None:
    mine = add_goal(database_dsn, seeded.user)  # the topic is not part of this goal's roadmap

    with pytest.raises(psycopg.errors.CheckViolation):
        queue_as_learner(database_dsn, seeded.user, mine, seeded.topics[0])


def test_a_topic_of_a_superseded_roadmap_cannot_get_a_new_lesson_job(
    database_dsn: str, seeded: Seeded
) -> None:
    admin(database_dsn).execute(
        "update public.roadmaps set status = 'superseded' where id = %s", (seeded.roadmap,)
    )

    with pytest.raises(psycopg.errors.CheckViolation):
        queue_as_learner(database_dsn, seeded.user, seeded.goal, seeded.topics[0])


def test_a_learner_cannot_queue_a_lesson_for_someone_elses_topic(
    database_dsn: str, seeded: Seeded
) -> None:
    bob = create_auth_user(database_dsn)
    bobs_goal = add_goal(database_dsn, bob)

    with pytest.raises(CONSTRAINT_VIOLATIONS):
        queue_as_learner(database_dsn, bob, bobs_goal, seeded.topics[0])
    with pytest.raises(CONSTRAINT_VIOLATIONS):
        queue_as_learner(database_dsn, bob, seeded.goal, seeded.topics[0])


def test_only_one_lesson_job_can_be_active_per_topic(database_dsn: str, seeded: Seeded) -> None:
    add_lesson_job(database_dsn, seeded, seeded.topics[0], status="running")

    with pytest.raises(psycopg.errors.UniqueViolation):
        add_lesson_job(database_dsn, seeded, seeded.topics[0])


def test_other_topics_and_roadmap_jobs_are_not_blocked_by_an_active_lesson(
    database_dsn: str, seeded: Seeded
) -> None:
    add_lesson_job(database_dsn, seeded, seeded.topics[0], status="running")

    add_lesson_job(database_dsn, seeded, seeded.topics[1])  # another topic
    add_job(database_dsn, seeded.user, seeded.goal)  # a roadmap job for the same goal


def test_a_new_lesson_job_is_allowed_once_the_last_one_has_finished(
    database_dsn: str, seeded: Seeded
) -> None:
    for status in ("failed", "cancelled", "completed"):
        add_lesson_job(database_dsn, seeded, seeded.topics[0], status=status)

    add_lesson_job(database_dsn, seeded, seeded.topics[0])


def test_there_is_still_only_one_active_roadmap_job_per_goal(
    database_dsn: str, seeded: Seeded
) -> None:
    add_job(database_dsn, seeded.user, seeded.goal)

    with pytest.raises(psycopg.errors.UniqueViolation):
        add_job(database_dsn, seeded.user, seeded.goal)


# --- Lessons: who can read and write ----------------------------------------------------------


def test_a_learner_reads_their_own_lessons_and_nobody_elses(
    database_dsn: str, seeded: Seeded
) -> None:
    lesson_for(database_dsn, seeded, seeded.topics[0])
    bob = create_auth_user(database_dsn)

    with admin(database_dsn).acting_as("authenticated", seeded.user) as connection:
        mine = connection.execute("select count(*) as n from public.lessons").fetchone()
    with admin(database_dsn).acting_as("authenticated", bob) as connection:
        theirs = connection.execute("select count(*) as n from public.lessons").fetchone()

    assert mine == {"n": 1}
    assert theirs == {"n": 0}


def test_anonymous_visitors_cannot_touch_lessons_at_all(database_dsn: str, seeded: Seeded) -> None:
    lesson_for(database_dsn, seeded, seeded.topics[0])

    with admin(database_dsn).acting_as("anon") as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("select * from public.lessons")


@pytest.mark.parametrize(
    "statement",
    [
        "update public.lessons set title = 'Hacked' where user_id = %s",
        "update public.lessons set status = 'superseded' where user_id = %s",
        "update public.lessons set content = '{}'::jsonb where user_id = %s",
        "delete from public.lessons where user_id = %s",
    ],
)
def test_a_learner_cannot_change_or_delete_a_stored_lesson(
    database_dsn: str, seeded: Seeded, statement: LiteralString
) -> None:
    lesson_for(database_dsn, seeded, seeded.topics[0])

    with admin(database_dsn).acting_as("authenticated", seeded.user) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(statement, (seeded.user,))


def test_a_learner_cannot_write_a_lesson_of_their_own(database_dsn: str, seeded: Seeded) -> None:
    job = add_lesson_job(database_dsn, seeded, seeded.topics[0])

    with admin(database_dsn).acting_as("authenticated", seeded.user) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "insert into public.lessons (user_id, roadmap_id, item_id, job_id, version, title,"
                " language, content, content_version, section_ids, prompt_version, provider,"
                " model_id) values"
                " (%s, %s, %s, %s, 1, 'Mine', 'en', '{}', 1, '{s1}', 'x', 'x', 'x')",
                (seeded.user, seeded.roadmap, seeded.topics[0], job),
            )


# --- Lessons: what is always true -------------------------------------------------------------


def test_a_topic_can_have_many_versions_but_only_one_is_current(
    database_dsn: str, seeded: Seeded
) -> None:
    lesson_for(database_dsn, seeded, seeded.topics[0], version=1, status="superseded")
    lesson_for(database_dsn, seeded, seeded.topics[0], version=2, status="superseded")
    lesson_for(database_dsn, seeded, seeded.topics[0], version=3)

    with pytest.raises(psycopg.errors.UniqueViolation):
        lesson_for(database_dsn, seeded, seeded.topics[0], version=4)  # a second current one


def test_version_numbers_are_unique_per_topic(database_dsn: str, seeded: Seeded) -> None:
    lesson_for(database_dsn, seeded, seeded.topics[0], version=1, status="superseded")

    with pytest.raises(psycopg.errors.UniqueViolation):
        lesson_for(database_dsn, seeded, seeded.topics[0], version=1)

    lesson_for(database_dsn, seeded, seeded.topics[1], version=1)  # another topic starts at 1


def test_one_job_can_store_only_one_lesson(database_dsn: str, seeded: Seeded) -> None:
    job = add_lesson_job(database_dsn, seeded, seeded.topics[0], status="completed")
    add_lesson(database_dsn, seeded.user, seeded.roadmap, seeded.topics[0], job)

    with pytest.raises(psycopg.errors.UniqueViolation):
        add_lesson(
            database_dsn, seeded.user, seeded.roadmap, seeded.topics[0], job, version=2,
            status="superseded",
        )  # fmt: skip


def test_a_lesson_must_belong_to_an_item_of_its_own_roadmap(
    database_dsn: str, seeded: Seeded
) -> None:
    other_job = add_job(database_dsn, seeded.user, seeded.goal, status="completed")
    other_roadmap = add_roadmap(
        database_dsn, seeded.user, seeded.goal, other_job, version=2, status="superseded"
    )
    job = add_lesson_job(database_dsn, seeded, seeded.topics[0], status="completed")

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        add_lesson(database_dsn, seeded.user, other_roadmap, seeded.topics[0], job)


def test_a_lesson_cannot_name_another_learners_job_or_roadmap(
    database_dsn: str, seeded: Seeded
) -> None:
    other = seed_learning_state(database_dsn)
    job = add_lesson_job(database_dsn, other, other.topics[0], status="completed")

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        add_lesson(database_dsn, seeded.user, seeded.roadmap, seeded.topics[0], job)


@pytest.mark.parametrize(
    "fields",
    [
        {"section_ids": []},
        {"section_ids": [f"s{n}" for n in range(1, 14)]},
        {"content": Jsonb([1, 2])},
        {"adjust": "angrier"},
        {"language": "english"},
        {"title": "   "},
        {"revision_feedback": "x" * 301},
        {"version": 0},
        {"status": "draft"},
    ],
)
def test_malformed_lesson_rows_are_refused_by_the_database(
    database_dsn: str, seeded: Seeded, fields: dict[str, object]
) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        lesson_for(database_dsn, seeded, seeded.topics[0], **fields)


def test_a_regeneration_can_point_back_at_the_version_it_started_from(
    database_dsn: str, seeded: Seeded
) -> None:
    first = lesson_for(database_dsn, seeded, seeded.topics[0], status="superseded")

    second = lesson_for(
        database_dsn,
        seeded,
        seeded.topics[0],
        version=2,
        based_on_lesson_id=first,
        adjust="simpler",
    )

    row = admin(database_dsn).fetchone("select * from public.lessons where id = %s", (second,))
    assert row is not None and row["based_on_lesson_id"] == first and row["adjust"] == "simpler"


def test_deleting_the_goal_removes_its_lessons_progress_and_jobs(
    database_dsn: str, seeded: Seeded
) -> None:
    lesson = lesson_for(database_dsn, seeded, seeded.topics[0])
    admin(database_dsn).execute(
        "insert into public.lesson_progress (lesson_id, user_id) values (%s, %s)",
        (lesson, seeded.user),
    )

    admin(database_dsn).execute("delete from public.learning_goals where id = %s", (seeded.goal,))

    for table in ("lessons", "lesson_progress", "generation_jobs"):
        count = admin(database_dsn).scalar(
            sql.SQL("select count(*) from public.{} where user_id = %s").format(
                sql.Identifier(table)
            ),
            (seeded.user,),
        )
        assert count == 0, table


# --- Progress ---------------------------------------------------------------------------------

INSERT_PROGRESS = (
    "insert into public.lesson_progress"
    " (lesson_id, user_id, status, completed_section_ids, current_section_id, completed_at)"
    " values (%s, %s, %s, %s, %s, %s) returning *"
)


@pytest.fixture
def lesson(database_dsn: str, seeded: Seeded) -> uuid.UUID:
    return lesson_for(database_dsn, seeded, seeded.topics[0])


def sections_of(dsn: str, lesson: uuid.UUID) -> list[str]:
    return list(
        admin(dsn).scalar("select section_ids from public.lessons where id = %s", (lesson,))
    )


def test_a_learner_can_record_progress_in_their_own_lesson(
    database_dsn: str, seeded: Seeded, lesson: uuid.UUID
) -> None:
    sections = sections_of(database_dsn, lesson)

    with admin(database_dsn).acting_as("authenticated", seeded.user) as connection:
        row = connection.execute(
            INSERT_PROGRESS, (lesson, seeded.user, "in_progress", sections[:1], sections[1], None)
        ).fetchone()

    assert row is not None
    assert row["status"] == "in_progress"
    assert row["completed_section_ids"] == sections[:1]
    assert row["current_section_id"] == sections[1]
    assert row["last_studied_at"] is not None and row["started_at"] is not None


def test_progress_can_be_updated_and_finished(
    database_dsn: str, seeded: Seeded, lesson: uuid.UUID
) -> None:
    sections = sections_of(database_dsn, lesson)

    with admin(database_dsn).acting_as("authenticated", seeded.user) as connection:
        connection.execute(INSERT_PROGRESS, (lesson, seeded.user, "in_progress", [], None, None))
        row = connection.execute(
            "update public.lesson_progress set status = 'completed', completed_at = now(),"
            " completed_section_ids = %s where lesson_id = %s returning *",
            (sections, lesson),
        ).fetchone()

    assert row is not None and row["status"] == "completed" and row["completed_at"] is not None


@pytest.mark.parametrize(
    ("done", "current", "message"),
    [
        (["s99"], None, "own lesson"),
        ([], "s99", "own lesson"),
        (["s1", "s1"], None, "only be marked done once"),
    ],
)
def test_progress_can_only_name_the_lessons_own_sections_once(
    database_dsn: str,
    seeded: Seeded,
    lesson: uuid.UUID,
    done: list[str],
    current: str | None,
    message: str,
) -> None:
    with admin(database_dsn).acting_as("authenticated", seeded.user) as connection:
        with pytest.raises(psycopg.errors.CheckViolation, match=message):
            connection.execute(
                INSERT_PROGRESS, (lesson, seeded.user, "in_progress", done, current, None)
            )


def test_a_lesson_is_only_complete_when_every_section_is_done(
    database_dsn: str, seeded: Seeded, lesson: uuid.UUID
) -> None:
    sections = sections_of(database_dsn, lesson)

    with admin(database_dsn).acting_as("authenticated", seeded.user) as connection:
        with pytest.raises(psycopg.errors.CheckViolation, match="every section"):
            connection.execute(
                "insert into public.lesson_progress (lesson_id, user_id, status,"
                " completed_section_ids, completed_at) values (%s, %s, 'completed', %s, now())",
                (lesson, seeded.user, sections[:-1]),
            )


def test_completed_and_its_timestamp_always_agree(
    database_dsn: str, seeded: Seeded, lesson: uuid.UUID
) -> None:
    sections = sections_of(database_dsn, lesson)

    with admin(database_dsn).acting_as("authenticated", seeded.user) as connection:
        with pytest.raises(psycopg.errors.CheckViolation, match="completed_matches_status"):
            connection.execute(
                INSERT_PROGRESS, (lesson, seeded.user, "completed", sections, None, None)
            )


def test_a_learner_cannot_record_progress_in_someone_elses_lesson(
    database_dsn: str, seeded: Seeded, lesson: uuid.UUID
) -> None:
    bob = create_auth_user(database_dsn)

    with admin(database_dsn).acting_as("authenticated", bob) as connection:
        with pytest.raises(CONSTRAINT_VIOLATIONS):
            connection.execute(INSERT_PROGRESS, (lesson, bob, "in_progress", [], None, None))
    # Naming Alice as the owner is refused too (the lesson is invisible to Bob, and row security
    # would refuse the row even if it were not).
    with admin(database_dsn).acting_as("authenticated", bob) as connection:
        with pytest.raises((psycopg.errors.InsufficientPrivilege, *CONSTRAINT_VIOLATIONS)):
            connection.execute(
                INSERT_PROGRESS, (lesson, seeded.user, "in_progress", [], None, None)
            )


def test_a_learner_cannot_read_or_change_someone_elses_progress(
    database_dsn: str, seeded: Seeded, lesson: uuid.UUID
) -> None:
    admin(database_dsn).execute(
        "insert into public.lesson_progress (lesson_id, user_id) values (%s, %s)",
        (lesson, seeded.user),
    )
    bob = create_auth_user(database_dsn)

    with admin(database_dsn).acting_as("authenticated", bob) as connection:
        seen = connection.execute("select count(*) as n from public.lesson_progress").fetchone()
        changed = connection.execute(
            "update public.lesson_progress set current_section_id = 's1' returning lesson_id"
        ).fetchall()

    assert seen == {"n": 0}
    assert changed == []


@pytest.mark.parametrize("column", ["started_at", "last_studied_at"])
def test_a_learner_cannot_set_the_study_timestamps(
    database_dsn: str, seeded: Seeded, lesson: uuid.UUID, column: str
) -> None:
    statement = sql.SQL(
        "insert into public.lesson_progress (lesson_id, user_id, {}) "
        "values (%s, %s, now() - interval '1 year')"
    ).format(sql.Identifier(column))

    with admin(database_dsn).acting_as("authenticated", seeded.user) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(statement, (lesson, seeded.user))


def test_progress_is_read_only_once_the_goal_is_archived(
    database_dsn: str, seeded: Seeded, lesson: uuid.UUID
) -> None:
    admin(database_dsn).execute(
        "insert into public.lesson_progress (lesson_id, user_id) values (%s, %s)",
        (lesson, seeded.user),
    )
    admin(database_dsn).execute(
        "update public.learning_goals set status = 'archived' where id = %s", (seeded.goal,)
    )

    with admin(database_dsn).acting_as("authenticated", seeded.user) as connection:
        with pytest.raises(psycopg.errors.CheckViolation, match="archived"):
            connection.execute(
                "update public.lesson_progress set current_section_id = 's1' where lesson_id = %s",
                (lesson,),
            )
    with admin(database_dsn).acting_as("authenticated", seeded.user) as connection:
        still_readable = connection.execute(
            "select count(*) as n from public.lesson_progress"
        ).fetchone()
    assert still_readable == {"n": 1}
