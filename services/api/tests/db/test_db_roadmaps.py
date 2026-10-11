"""Roadmap tables: versioning, ownership, immutability and shape rules, enforced by PostgreSQL."""

import uuid
from typing import Any, LiteralString, cast

import psycopg.errors
import pytest

from support.database import admin, create_auth_user
from support.rows import add_goal, add_item, add_job, add_module, add_roadmap


def plan_for(
    dsn: str, user_id: uuid.UUID, *, goal_id: uuid.UUID | None = None
) -> tuple[uuid.UUID, uuid.UUID]:
    """(goal_id, roadmap_id) for a goal with one finished job and one current roadmap."""
    goal = goal_id or add_goal(dsn, user_id)
    job = add_job(dsn, user_id, goal, status="completed")
    return goal, add_roadmap(dsn, user_id, goal, job)


# --- Versioning ------------------------------------------------------------------------------


def test_versions_are_unique_per_goal(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)
    goal, _ = plan_for(database_dsn, alice)

    with pytest.raises(psycopg.errors.UniqueViolation):
        add_roadmap(
            database_dsn,
            alice,
            goal,
            add_job(database_dsn, alice, goal, status="completed"),
            version=1,
            status="superseded",
        )


def test_each_goal_counts_its_own_versions(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)

    plan_for(database_dsn, alice)
    plan_for(database_dsn, alice)  # a different goal, also version 1


def test_a_job_can_produce_only_one_roadmap(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)
    goal = add_goal(database_dsn, alice)
    job = add_job(database_dsn, alice, goal, status="completed")
    add_roadmap(database_dsn, alice, goal, job, version=1, status="superseded")

    with pytest.raises(psycopg.errors.UniqueViolation):
        add_roadmap(database_dsn, alice, goal, job, version=2, status="current")


def test_only_one_version_can_be_current(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)
    goal, _ = plan_for(database_dsn, alice)

    with pytest.raises(psycopg.errors.UniqueViolation):
        add_roadmap(
            database_dsn,
            alice,
            goal,
            add_job(database_dsn, alice, goal, status="completed"),
            version=2,
            status="current",
        )


def test_older_versions_are_kept_when_a_newer_one_is_stored(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)
    goal, first = plan_for(database_dsn, alice)
    admin(database_dsn).execute(
        "update public.roadmaps set status = 'superseded' where id = %s", (first,)
    )

    second = add_roadmap(
        database_dsn, alice, goal, add_job(database_dsn, alice, goal, status="completed"), version=2
    )

    rows = admin(database_dsn).fetchall(
        "select id, version, status from public.roadmaps where goal_id = %s order by version",
        (goal,),
    )
    assert [(r["id"], r["version"], r["status"]) for r in rows] == [
        (first, 1, "superseded"),
        (second, 2, "current"),
    ]


@pytest.mark.parametrize("version", [0, -1])
def test_versions_start_at_one(database_dsn: str, version: int) -> None:
    alice = create_auth_user(database_dsn)
    goal = add_goal(database_dsn, alice)
    job = add_job(database_dsn, alice, goal, status="completed")

    with pytest.raises(psycopg.errors.CheckViolation):
        add_roadmap(database_dsn, alice, goal, job, version=version)


def test_the_revision_lineage_survives_but_clears_when_the_parent_is_deleted(
    database_dsn: str,
) -> None:
    alice = create_auth_user(database_dsn)
    goal, first = plan_for(database_dsn, alice)
    admin(database_dsn).execute(
        "update public.roadmaps set status = 'superseded' where id = %s", (first,)
    )
    second = add_roadmap(
        database_dsn,
        alice,
        goal,
        add_job(database_dsn, alice, goal, status="completed"),
        version=2,
        based_on_roadmap_id=first,
    )

    admin(database_dsn).execute("delete from public.roadmaps where id = %s", (first,))

    row = admin(database_dsn).fetchone(
        "select based_on_roadmap_id, user_id from public.roadmaps where id = %s", (second,)
    )
    assert row == {"based_on_roadmap_id": None, "user_id": alice}


# --- Ownership -------------------------------------------------------------------------------


def test_a_roadmap_cannot_hang_off_someone_elses_goal(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)
    bob = create_auth_user(database_dsn)
    goal = add_goal(database_dsn, alice)
    job = add_job(database_dsn, alice, goal, status="completed")

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        add_roadmap(database_dsn, bob, goal, job)


def test_a_roadmap_cannot_claim_someone_elses_job(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)
    bob = create_auth_user(database_dsn)
    alice_job = add_job(database_dsn, alice, add_goal(database_dsn, alice), status="completed")
    bob_goal = add_goal(database_dsn, bob)

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        add_roadmap(database_dsn, bob, bob_goal, alice_job)


def test_a_learner_reads_only_their_own_plans(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)
    bob = create_auth_user(database_dsn)
    _, alice_roadmap = plan_for(database_dsn, alice)
    plan_for(database_dsn, bob)
    module = add_module(database_dsn, alice, alice_roadmap)
    item = add_item(database_dsn, alice, alice_roadmap, module_id=module)

    with admin(database_dsn).acting_as("authenticated", alice) as connection:
        roadmaps = connection.execute("select id from public.roadmaps").fetchall()
        modules = connection.execute("select id from public.roadmap_modules").fetchall()
        items = connection.execute("select id from public.roadmap_items").fetchall()
    with admin(database_dsn).acting_as("authenticated", bob) as connection:
        bobs_modules = connection.execute("select id from public.roadmap_modules").fetchall()
        bobs_items = connection.execute("select id from public.roadmap_items").fetchall()
        bobs_view = connection.execute(
            "select id from public.roadmaps where id = %s", (alice_roadmap,)
        ).fetchall()

    assert [r["id"] for r in roadmaps] == [alice_roadmap]
    assert [m["id"] for m in modules] == [module]
    assert [i["id"] for i in items] == [item]
    assert bobs_modules == [] and bobs_items == [] and bobs_view == []


def test_anonymous_visitors_cannot_read_any_roadmap_table(database_dsn: str) -> None:
    for table in ("roadmaps", "roadmap_modules", "roadmap_items", "roadmap_item_prerequisites"):
        with admin(database_dsn).acting_as("anon") as connection:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute(f"select * from public.{table}")  # noqa: S608


# --- Immutability ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "statement",
    [
        "insert into public.roadmaps (user_id) values (gen_random_uuid())",
        "delete from public.roadmaps",
        "insert into public.roadmap_modules (user_id) values (gen_random_uuid())",
        "update public.roadmap_modules set title = 'x'",
        "delete from public.roadmap_modules",
        "insert into public.roadmap_items (user_id) values (gen_random_uuid())",
        "update public.roadmap_items set title = 'x'",
        "delete from public.roadmap_items",
        "delete from public.roadmap_item_prerequisites",
        "insert into public.roadmap_item_prerequisites (user_id) values (gen_random_uuid())",
    ],
)
def test_learners_cannot_write_plans_directly(database_dsn: str, statement: str) -> None:
    alice = create_auth_user(database_dsn)
    plan_for(database_dsn, alice)

    with admin(database_dsn).acting_as("authenticated", alice) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(cast(LiteralString, statement))


@pytest.mark.parametrize(
    "assignment",
    [
        "title = 'Rewritten'",
        "overview = 'Rewritten'",
        "version = 99",
        "total_minutes = 1",
        "objectives = '[]'",
        "job_id = gen_random_uuid()",
        "user_id = gen_random_uuid()",
        "is_synthetic = false",
    ],
)
def test_a_stored_roadmaps_content_cannot_be_edited_by_the_learner(
    database_dsn: str, assignment: str
) -> None:
    alice = create_auth_user(database_dsn)
    _, roadmap = plan_for(database_dsn, alice)

    with admin(database_dsn).acting_as("authenticated", alice) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                cast(LiteralString, f"update public.roadmaps set {assignment} where id = %s"),  # noqa: S608
                (roadmap,),
            )


# --- Switching the current version -----------------------------------------------------------


def two_versions(dsn: str, user_id: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    goal, first = plan_for(dsn, user_id)
    admin(dsn).execute("update public.roadmaps set status = 'superseded' where id = %s", (first,))
    second = add_roadmap(
        dsn, user_id, goal, add_job(dsn, user_id, goal, status="completed"), version=2
    )
    return goal, first, second


def test_a_learner_can_switch_which_version_is_current(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)
    goal, first, second = two_versions(database_dsn, alice)

    with admin(database_dsn).acting_as("authenticated", alice) as connection:
        connection.execute(
            "update public.roadmaps set status = 'superseded' where id = %s", (second,)
        )
        connection.execute("update public.roadmaps set status = 'current' where id = %s", (first,))
        # (acting_as always rolls back, so the result is read inside the transaction.)
        rows = connection.execute(
            "select id, status from public.roadmaps where goal_id = %s", (goal,)
        ).fetchall()

    assert {r["id"]: r["status"] for r in rows} == {first: "current", second: "superseded"}


def test_switching_cannot_leave_two_current_versions(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)
    _, first, _ = two_versions(database_dsn, alice)

    with admin(database_dsn).acting_as("authenticated", alice) as connection:
        with pytest.raises(psycopg.errors.UniqueViolation):
            connection.execute(
                "update public.roadmaps set status = 'current' where id = %s", (first,)
            )


def test_another_learner_cannot_switch_versions(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)
    bob = create_auth_user(database_dsn)
    _, first, second = two_versions(database_dsn, alice)

    with admin(database_dsn).acting_as("authenticated", bob) as connection:
        result = connection.execute(
            "update public.roadmaps set status = 'superseded' where id = %s", (second,)
        )
        assert result.rowcount == 0

    assert (
        admin(database_dsn).scalar("select status from public.roadmaps where id = %s", (second,))
        == "current"
    )
    assert (
        admin(database_dsn).scalar("select status from public.roadmaps where id = %s", (first,))
        == "superseded"
    )


def test_versions_of_an_archived_goal_cannot_be_switched(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)
    goal, _, second = two_versions(database_dsn, alice)
    admin(database_dsn).execute(
        "update public.learning_goals set status = 'archived' where id = %s", (goal,)
    )

    with admin(database_dsn).acting_as("authenticated", alice) as connection:
        with pytest.raises(psycopg.errors.CheckViolation) as caught:
            connection.execute(
                "update public.roadmaps set status = 'superseded' where id = %s", (second,)
            )

    assert caught.value.diag.constraint_name == "roadmaps_goal_archived_read_only"


def test_the_status_is_one_of_two_values(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)
    _, roadmap = plan_for(database_dsn, alice)

    with admin(database_dsn).acting_as("authenticated", alice) as connection:
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "update public.roadmaps set status = 'deleted' where id = %s", (roadmap,)
            )


# --- Content shape ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"title": "   "},
        {"language": "english"},
        {"syllabus_basis": "official_syllabus"},
        {"objectives": "[]"},
        {"objectives": '{"id": "o1"}'},
        {"evidence": '"cited"'},
        {"total_minutes": 0},
        {"total_days": 0},
        {"topic_count": 0},
        {"daily_minutes": 1},
        {"revision_feedback": "x" * 501},
        {"status": "published"},
    ],
)
def test_invalid_roadmap_values_are_refused(database_dsn: str, overrides: dict[str, Any]) -> None:
    alice = create_auth_user(database_dsn)
    goal = add_goal(database_dsn, alice)
    job = add_job(database_dsn, alice, goal, status="completed")

    with pytest.raises(psycopg.errors.CheckViolation):
        add_roadmap(database_dsn, alice, goal, job, **overrides)


def test_a_topic_needs_a_module_and_a_practice_task(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)
    _, roadmap = plan_for(database_dsn, alice)
    module = add_module(database_dsn, alice, roadmap)

    with pytest.raises(psycopg.errors.CheckViolation):
        add_item(database_dsn, alice, roadmap, module_id=None, kind="topic", position=1)
    with pytest.raises(psycopg.errors.CheckViolation):
        admin(database_dsn).execute(
            "insert into public.roadmap_items (user_id, roadmap_id, module_id, kind, position,"
            " item_key, title, description, estimated_minutes, day_number)"
            " values (%s, %s, %s, 'topic', 1, 'no-practice', 't', 'd', 30, 1)",
            (alice, roadmap, module),
        )


def test_enrichment_is_unscheduled_and_everything_else_is_scheduled(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)
    _, roadmap = plan_for(database_dsn, alice)
    module = add_module(database_dsn, alice, roadmap)

    add_item(database_dsn, alice, roadmap, module_id=None, kind="enrichment", position=1, day=None)
    with pytest.raises(psycopg.errors.CheckViolation):
        add_item(database_dsn, alice, roadmap, module_id=None, kind="enrichment", position=2, day=3)
    with pytest.raises(psycopg.errors.CheckViolation):
        add_item(database_dsn, alice, roadmap, module_id=module, kind="topic", position=3, day=None)
    with pytest.raises(psycopg.errors.CheckViolation):
        add_item(
            database_dsn, alice, roadmap, module_id=None, kind="revision", position=4, day=None
        )


@pytest.mark.parametrize(
    "key", ["Has Capitals", "has_underscore", "-leading", "trailing-", "double--hyphen", ""]
)
def test_item_keys_are_lowercase_words_joined_by_hyphens(database_dsn: str, key: str) -> None:
    alice = create_auth_user(database_dsn)
    _, roadmap = plan_for(database_dsn, alice)
    module = add_module(database_dsn, alice, roadmap)

    with pytest.raises(psycopg.errors.CheckViolation):
        add_item(database_dsn, alice, roadmap, module_id=module, key=key)


def test_positions_and_keys_are_unique_within_a_roadmap_but_not_across_roadmaps(
    database_dsn: str,
) -> None:
    alice = create_auth_user(database_dsn)
    _, first = plan_for(database_dsn, alice)
    _, second = plan_for(database_dsn, alice)
    first_module = add_module(database_dsn, alice, first)
    second_module = add_module(database_dsn, alice, second)
    add_item(database_dsn, alice, first, module_id=first_module, position=1, key="intro")

    with pytest.raises(psycopg.errors.UniqueViolation):
        add_item(database_dsn, alice, first, module_id=first_module, position=1, key="other")
    with pytest.raises(psycopg.errors.UniqueViolation):
        add_item(database_dsn, alice, first, module_id=first_module, position=2, key="intro")
    add_item(database_dsn, alice, second, module_id=second_module, position=1, key="intro")


def test_an_item_cannot_use_a_module_from_another_roadmap(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)
    _, first = plan_for(database_dsn, alice)
    _, second = plan_for(database_dsn, alice)
    foreign_module = add_module(database_dsn, alice, second)

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        add_item(database_dsn, alice, first, module_id=foreign_module)


def test_an_item_cannot_belong_to_a_different_user_than_its_roadmap(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)
    bob = create_auth_user(database_dsn)
    _, roadmap = plan_for(database_dsn, alice)

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        add_module(database_dsn, bob, roadmap)


# --- Prerequisites ---------------------------------------------------------------------------


def make_prerequisite(
    dsn: str, user_id: uuid.UUID, roadmap: uuid.UUID, item: uuid.UUID, prerequisite: uuid.UUID
) -> None:
    admin(dsn).execute(
        "insert into public.roadmap_item_prerequisites"
        " (item_id, prerequisite_id, roadmap_id, user_id) values (%s, %s, %s, %s)",
        (item, prerequisite, roadmap, user_id),
    )


def test_prerequisites_link_items_of_the_same_roadmap(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)
    _, roadmap = plan_for(database_dsn, alice)
    module = add_module(database_dsn, alice, roadmap)
    first = add_item(database_dsn, alice, roadmap, module_id=module, position=1)
    second = add_item(database_dsn, alice, roadmap, module_id=module, position=2, day=2)

    make_prerequisite(database_dsn, alice, roadmap, second, first)

    with admin(database_dsn).acting_as("authenticated", alice) as connection:
        rows = connection.execute(
            "select item_id, prerequisite_id from public.roadmap_item_prerequisites"
        ).fetchall()
    assert rows == [{"item_id": second, "prerequisite_id": first}]


def test_an_item_cannot_be_its_own_prerequisite(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)
    _, roadmap = plan_for(database_dsn, alice)
    item = add_item(
        database_dsn, alice, roadmap, module_id=add_module(database_dsn, alice, roadmap)
    )

    with pytest.raises(psycopg.errors.CheckViolation):
        make_prerequisite(database_dsn, alice, roadmap, item, item)


def test_a_prerequisite_cannot_come_from_another_roadmap(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)
    _, first = plan_for(database_dsn, alice)
    _, second = plan_for(database_dsn, alice)
    mine = add_item(database_dsn, alice, first, module_id=add_module(database_dsn, alice, first))
    foreign = add_item(
        database_dsn, alice, second, module_id=add_module(database_dsn, alice, second)
    )

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        make_prerequisite(database_dsn, alice, first, mine, foreign)


# --- Cleanup ---------------------------------------------------------------------------------


def test_deleting_a_goal_removes_every_part_of_its_plans(database_dsn: str) -> None:
    alice = create_auth_user(database_dsn)
    goal = add_goal(database_dsn, alice, status="archived")
    job = add_job(database_dsn, alice, goal, status="completed")
    roadmap = add_roadmap(database_dsn, alice, goal, job)
    module = add_module(database_dsn, alice, roadmap)
    first = add_item(database_dsn, alice, roadmap, module_id=module, position=1)
    second = add_item(database_dsn, alice, roadmap, module_id=module, position=2, day=2)
    make_prerequisite(database_dsn, alice, roadmap, second, first)

    admin(database_dsn).execute("delete from public.learning_goals where id = %s", (goal,))

    for table in (
        "roadmaps",
        "roadmap_modules",
        "roadmap_items",
        "roadmap_item_prerequisites",
        "generation_jobs",
    ):
        assert (
            admin(database_dsn).scalar(
                f"select count(*) from public.{table} where user_id = %s",  # noqa: S608
                (alice,),
            )
            == 0
        ), table
