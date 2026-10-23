"""Flashcards in the database: who can write what, and what is always true (ADR-050)."""

import uuid
from typing import Any

import psycopg.errors
import pytest
from psycopg import sql

from support.database import admin, create_auth_user
from support.lessons import Seeded, seed_learning_state
from support.rows import add_goal

INSERT_CARD = (
    "insert into public.flashcards (user_id, goal_id, item_id, front, back)"
    " values (%s, %s, %s, %s, %s) returning *"
)
INSERT_REVIEW = (
    "insert into public.flashcard_reviews (user_id, card_id, rating, scheduler_version,"
    " interval_before, ease_before, interval_after, ease_after, repetitions_after, lapses_after,"
    " due_after, idempotency_key)"
    " values (%s, %s, 'good', 'sm2-v1', 0, 2.50, 1, 2.50, 1, 0, now() + interval '1 day', %s)"
    " returning *"
)
CONSTRAINT_VIOLATIONS = (psycopg.errors.CheckViolation, psycopg.errors.ForeignKeyViolation)


@pytest.fixture
def seeded(database_dsn: str) -> Seeded:
    return seed_learning_state(database_dsn)


def add_card(dsn: str, seeded: Seeded, **fields: Any) -> uuid.UUID:
    """A card written by the superuser, so tests can start from one without going through RLS."""
    values = {
        "user_id": seeded.user,
        "goal_id": seeded.goal,
        "front": "What is ownership?",
        "back": "Each value has exactly one owner.",
        **fields,
    }
    query = sql.SQL("insert into public.flashcards ({}) values ({}) returning id").format(
        sql.SQL(", ").join(sql.Identifier(column) for column in values),
        sql.SQL(", ").join(sql.Placeholder() * len(values)),
    )
    row = admin(dsn).fetchone(query, tuple(values.values()))
    assert row is not None
    return row["id"]


# --- Creating cards -----------------------------------------------------------------------------


def test_a_learner_can_create_a_card_and_it_starts_due_with_default_scheduling(
    database_dsn: str, seeded: Seeded
) -> None:
    with admin(database_dsn).acting_as("authenticated", seeded.user) as connection:
        card = connection.execute(
            INSERT_CARD, (seeded.user, seeded.goal, None, "  Front  ", "Back")
        ).fetchone()

    assert card is not None
    assert card["front"] == "  Front  "
    assert card["interval_days"] == 0
    assert float(card["ease_factor"]) == 2.5
    assert card["repetitions"] == 0 and card["lapses"] == 0
    assert card["last_reviewed_at"] is None
    assert card["origin"] == "manual"
    assert card["scheduler_version"] == "sm2-v1"


def test_a_card_can_name_a_topic_of_its_own_goal(database_dsn: str, seeded: Seeded) -> None:
    with admin(database_dsn).acting_as("authenticated", seeded.user) as connection:
        card = connection.execute(
            INSERT_CARD, (seeded.user, seeded.goal, seeded.topics[0], "Front", "Back")
        ).fetchone()

    assert card is not None and card["item_id"] == seeded.topics[0]


def test_a_card_cannot_name_a_topic_of_a_different_goal(database_dsn: str, seeded: Seeded) -> None:
    other_goal = add_goal(database_dsn, seeded.user)

    with (
        pytest.raises(psycopg.errors.CheckViolation),
        admin(database_dsn).acting_as("authenticated", seeded.user) as connection,
    ):
        connection.execute(
            INSERT_CARD, (seeded.user, other_goal, seeded.topics[0], "Front", "Back")
        )


def test_a_card_cannot_be_moved_to_another_goal_by_a_learner(
    database_dsn: str, seeded: Seeded
) -> None:
    card = add_card(database_dsn, seeded, item_id=seeded.topics[0])
    other_goal = add_goal(database_dsn, seeded.user)

    with (
        pytest.raises(psycopg.errors.InsufficientPrivilege),
        admin(database_dsn).acting_as("authenticated", seeded.user) as connection,
    ):
        connection.execute(
            "update public.flashcards set goal_id = %s where id = %s", (other_goal, card)
        )


def test_a_card_cannot_be_re_pointed_at_a_topic_of_a_different_goal(
    database_dsn: str, seeded: Seeded
) -> None:
    other = seed_learning_state(database_dsn)
    card = add_card(database_dsn, seeded)

    with (
        pytest.raises(CONSTRAINT_VIOLATIONS),
        admin(database_dsn).acting_as("authenticated", seeded.user) as connection,
    ):
        connection.execute(
            "update public.flashcards set item_id = %s where id = %s", (other.topics[0], card)
        )


@pytest.mark.parametrize(
    ("front", "back"),
    [("", "Back"), ("   ", "Back"), ("Front", ""), ("Front", "   "), ("x" * 1001, "Back")],
)
def test_a_blank_or_oversized_side_is_refused(
    database_dsn: str, seeded: Seeded, front: str, back: str
) -> None:
    with (
        pytest.raises(psycopg.errors.CheckViolation),
        admin(database_dsn).acting_as("authenticated", seeded.user) as connection,
    ):
        connection.execute(INSERT_CARD, (seeded.user, seeded.goal, None, front, back))


def test_the_back_of_a_card_may_be_longer_than_the_front(database_dsn: str, seeded: Seeded) -> None:
    with admin(database_dsn).acting_as("authenticated", seeded.user) as connection:
        connection.execute(INSERT_CARD, (seeded.user, seeded.goal, None, "F", "b" * 2000))

    with (
        pytest.raises(psycopg.errors.CheckViolation),
        admin(database_dsn).acting_as("authenticated", seeded.user) as connection,
    ):
        connection.execute(INSERT_CARD, (seeded.user, seeded.goal, None, "F", "b" * 2001))


def test_a_learner_cannot_choose_the_schedule_when_creating_a_card(
    database_dsn: str, seeded: Seeded
) -> None:
    with (
        pytest.raises(psycopg.errors.InsufficientPrivilege),
        admin(database_dsn).acting_as("authenticated", seeded.user) as connection,
    ):
        connection.execute(
            "insert into public.flashcards (user_id, goal_id, front, back, due_at)"
            " values (%s, %s, 'F', 'B', now() + interval '30 days')",
            (seeded.user, seeded.goal),
        )


# --- Ownership ------------------------------------------------------------------------------------


def test_a_learner_cannot_create_a_card_for_someone_elses_goal(
    database_dsn: str, seeded: Seeded
) -> None:
    mallory = create_auth_user(database_dsn)

    with (
        pytest.raises(CONSTRAINT_VIOLATIONS),
        admin(database_dsn).acting_as("authenticated", mallory) as connection,
    ):
        connection.execute(INSERT_CARD, (mallory, seeded.goal, None, "F", "B"))


def test_a_learner_cannot_create_a_card_in_someone_elses_name(
    database_dsn: str, seeded: Seeded
) -> None:
    mallory = create_auth_user(database_dsn)

    with (
        pytest.raises(psycopg.errors.InsufficientPrivilege),
        admin(database_dsn).acting_as("authenticated", mallory) as connection,
    ):
        connection.execute(INSERT_CARD, (seeded.user, seeded.goal, None, "F", "B"))


def test_cards_are_invisible_to_other_learners_and_cannot_be_changed_by_them(
    database_dsn: str, seeded: Seeded
) -> None:
    card = add_card(database_dsn, seeded)
    mallory = create_auth_user(database_dsn)

    with admin(database_dsn).acting_as("authenticated", mallory) as connection:
        assert connection.execute("select * from public.flashcards").fetchall() == []
        assert (
            connection.execute(
                "update public.flashcards set front = 'hacked' where id = %s returning id", (card,)
            ).fetchall()
            == []
        )
        assert (
            connection.execute(
                "delete from public.flashcards where id = %s returning id", (card,)
            ).fetchall()
            == []
        )

    assert admin(database_dsn).scalar("select front from public.flashcards where id = %s", (card,))


def test_anon_has_no_access_to_cards_or_reviews(database_dsn: str, seeded: Seeded) -> None:
    add_card(database_dsn, seeded)

    for table in ("flashcards", "flashcard_reviews"):
        with (
            pytest.raises(psycopg.errors.InsufficientPrivilege),
            admin(database_dsn).acting_as("anon") as connection,
        ):
            connection.execute(f"select * from public.{table}")  # noqa: S608


# --- Editing and the schedule ------------------------------------------------------------------


def test_a_learner_can_edit_their_card_and_updated_at_moves(
    database_dsn: str, seeded: Seeded
) -> None:
    card = add_card(database_dsn, seeded)
    before = admin(database_dsn).scalar(
        "select updated_at from public.flashcards where id = %s", (card,)
    )

    with admin(database_dsn).acting_as("authenticated", seeded.user) as connection:
        row = connection.execute(
            "update public.flashcards set front = 'New front', back = 'New back'"
            " where id = %s returning front, back, updated_at",
            (card,),
        ).fetchone()

    assert row is not None
    assert (row["front"], row["back"]) == ("New front", "New back")
    assert row["updated_at"] > before


def test_a_learner_cannot_change_a_cards_owner_or_goal_identity_columns(
    database_dsn: str, seeded: Seeded
) -> None:
    card = add_card(database_dsn, seeded)
    mallory = create_auth_user(database_dsn)

    with (
        pytest.raises(psycopg.errors.InsufficientPrivilege),
        admin(database_dsn).acting_as("authenticated", seeded.user) as connection,
    ):
        connection.execute(
            "update public.flashcards set user_id = %s where id = %s", (mallory, card)
        )


@pytest.mark.parametrize(
    "assignment",
    ["interval_days = 366", "interval_days = -1", "ease_factor = 1.29", "ease_factor = 3.51"],
)
def test_the_schedule_stays_within_its_bounds(
    database_dsn: str, seeded: Seeded, assignment: str
) -> None:
    card = add_card(database_dsn, seeded)

    with (
        pytest.raises(psycopg.errors.CheckViolation),
        admin(database_dsn).acting_as("authenticated", seeded.user) as connection,
    ):
        column, value = assignment.split(" = ")
        connection.execute(
            sql.SQL("update public.flashcards set {} = %s where id = %s").format(
                sql.Identifier(column)
            ),
            (value, card),
        )


# --- Review history -----------------------------------------------------------------------------


def test_a_learner_can_record_a_review_of_their_own_card(database_dsn: str, seeded: Seeded) -> None:
    card = add_card(database_dsn, seeded)

    with admin(database_dsn).acting_as("authenticated", seeded.user) as connection:
        review = connection.execute(INSERT_REVIEW, (seeded.user, card, "key-12345678")).fetchone()
        seen = connection.execute("select count(*) as n from public.flashcard_reviews").fetchone()

    assert review is not None and review["rating"] == "good"
    assert seen is not None and seen["n"] == 1


def test_a_review_of_someone_elses_card_is_refused(database_dsn: str, seeded: Seeded) -> None:
    card = add_card(database_dsn, seeded)
    mallory = create_auth_user(database_dsn)

    with (
        pytest.raises(CONSTRAINT_VIOLATIONS),
        admin(database_dsn).acting_as("authenticated", mallory) as connection,
    ):
        connection.execute(INSERT_REVIEW, (mallory, card, "key-12345678"))


def test_review_history_cannot_be_changed_or_deleted_by_a_learner(
    database_dsn: str, seeded: Seeded
) -> None:
    card = add_card(database_dsn, seeded)
    admin(database_dsn).execute(INSERT_REVIEW, (seeded.user, card, "key-12345678"))

    for statement in (
        "update public.flashcard_reviews set rating = 'easy'",
        "delete from public.flashcard_reviews",
    ):
        with (
            pytest.raises(psycopg.errors.InsufficientPrivilege),
            admin(database_dsn).acting_as("authenticated", seeded.user) as connection,
        ):
            connection.execute(statement)  # type: ignore[arg-type]


def test_reviews_are_invisible_to_other_learners(database_dsn: str, seeded: Seeded) -> None:
    card = add_card(database_dsn, seeded)
    admin(database_dsn).execute(INSERT_REVIEW, (seeded.user, card, "key-12345678"))
    mallory = create_auth_user(database_dsn)

    with admin(database_dsn).acting_as("authenticated", mallory) as connection:
        assert connection.execute("select * from public.flashcard_reviews").fetchall() == []


def test_the_same_idempotency_key_on_the_same_card_is_one_review(
    database_dsn: str, seeded: Seeded
) -> None:
    card = add_card(database_dsn, seeded)
    other = add_card(database_dsn, seeded, front="Another")
    admin(database_dsn).execute(INSERT_REVIEW, (seeded.user, card, "key-12345678"))

    with pytest.raises(psycopg.errors.UniqueViolation):
        admin(database_dsn).execute(INSERT_REVIEW, (seeded.user, card, "key-12345678"))
    # The same key on a different card is a different review.
    admin(database_dsn).execute(INSERT_REVIEW, (seeded.user, other, "key-12345678"))


def test_a_review_must_record_a_known_rating_and_a_bounded_schedule(
    database_dsn: str, seeded: Seeded
) -> None:
    card = add_card(database_dsn, seeded)

    for statement in (
        INSERT_REVIEW.replace("'good'", "'perfect'"),
        INSERT_REVIEW.replace("1, 2.50, 1, 0", "400, 2.50, 1, 0"),
        INSERT_REVIEW.replace("2.50, 1, 2.50", "2.50, 1, 9.99"),
    ):
        with pytest.raises(psycopg.errors.CheckViolation):
            admin(database_dsn).execute(statement, (seeded.user, card, "key-12345678"))


# --- Deleting -------------------------------------------------------------------------------------


def test_deleting_a_card_removes_its_history(database_dsn: str, seeded: Seeded) -> None:
    card = add_card(database_dsn, seeded)
    admin(database_dsn).execute(INSERT_REVIEW, (seeded.user, card, "key-12345678"))

    with admin(database_dsn).acting_as("authenticated", seeded.user) as connection:
        connection.execute("delete from public.flashcards where id = %s", (card,))
        assert connection.execute("select * from public.flashcard_reviews").fetchall() == []


def test_deleting_a_goal_removes_its_cards_and_their_history(
    database_dsn: str, seeded: Seeded
) -> None:
    card = add_card(database_dsn, seeded)
    admin(database_dsn).execute(INSERT_REVIEW, (seeded.user, card, "key-12345678"))

    admin(database_dsn).execute("delete from public.learning_goals where id = %s", (seeded.goal,))

    # The database is shared with other tests, so look only at this learner's rows.
    assert (
        admin(database_dsn).scalar(
            "select count(*) from public.flashcards where user_id = %s", (seeded.user,)
        )
        == 0
    )
    assert (
        admin(database_dsn).scalar(
            "select count(*) from public.flashcard_reviews where user_id = %s", (seeded.user,)
        )
        == 0
    )
