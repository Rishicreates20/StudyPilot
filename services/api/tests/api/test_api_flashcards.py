"""Flashcards over HTTP: ownership, validation, limits, the schedule and idempotent reviews."""

from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response

from app.schemas.flashcards import MAX_CARDS_PER_GOAL
from conftest import Learner
from support.api_helpers import create_goal, generate_roadmap, set_status, topic_ids
from support.database import admin

MakeLearner = Callable[..., Learner]

CARD = {"front": "What is ownership?", "back": "Each value has exactly one owner."}


def add_card(api: TestClient, learner: Learner, goal_id: str, **body: Any) -> dict[str, Any]:
    response = api.post(
        f"/v1/goals/{goal_id}/flashcards", headers=learner.headers, json={**CARD, **body}
    )
    assert response.status_code == 201, response.text
    return response.json()


def review(
    api: TestClient, learner: Learner, card_id: str, rating: str = "good", *, key: str | None = None
) -> Response:
    headers = {**learner.headers, **({"Idempotency-Key": key} if key else {})}
    return api.post(f"/v1/flashcards/{card_id}/reviews", headers=headers, json={"rating": rating})


def parse(moment: str) -> datetime:
    return datetime.fromisoformat(moment)


@pytest.fixture
def world(api: TestClient, make_learner: MakeLearner) -> dict[str, Any]:
    alice, bob = make_learner(), make_learner()
    return {"alice": alice, "bob": bob, "goal": create_goal(api, alice)["id"]}


# --- Creating and reading --------------------------------------------------------------------


def test_a_new_card_is_due_at_once_with_the_default_schedule(
    api: TestClient, world: dict[str, Any]
) -> None:
    card = add_card(api, world["alice"], world["goal"], front="  Padded  ", back="  Answer  ")

    assert card["front"] == "Padded" and card["back"] == "Answer"
    assert card["goal_id"] == world["goal"]
    assert card["origin"] == "manual"
    assert card["is_due"] is True
    assert (card["interval_days"], card["repetitions"], card["lapses"]) == (0, 0, 0)
    assert card["ease_factor"] == 2.5
    assert card["last_reviewed_at"] is None
    assert card["scheduler_version"] == "sm2-v1"
    assert "user_id" not in card


def test_the_list_is_newest_first_and_the_summary_counts_the_deck(
    api: TestClient, world: dict[str, Any]
) -> None:
    first = add_card(api, world["alice"], world["goal"], front="First")
    second = add_card(api, world["alice"], world["goal"], front="Second")
    review(api, world["alice"], first["id"], "good")

    body = api.get(f"/v1/goals/{world['goal']}/flashcards", headers=world["alice"].headers).json()

    assert [c["front"] for c in body["cards"]] == ["Second", "First"]
    summary = body["summary"]
    assert summary["total"] == 2
    assert summary["due_now"] == 1  # the reviewed one is now tomorrow
    assert summary["reviewed_today"] == 1
    assert summary["next_due_at"] is not None
    assert summary["limit"] == MAX_CARDS_PER_GOAL
    assert body["cards"][0]["id"] == second["id"]


def test_an_empty_deck_has_an_empty_summary(api: TestClient, world: dict[str, Any]) -> None:
    body = api.get(f"/v1/goals/{world['goal']}/flashcards", headers=world["alice"].headers).json()

    assert body["cards"] == []
    assert body["summary"] == {
        "total": 0,
        "due_now": 0,
        "next_due_at": None,
        "reviewed_today": 0,
        "limit": MAX_CARDS_PER_GOAL,
    }


# --- Validation ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        {"front": "", "back": "B"},
        {"front": "   ", "back": "B"},
        {"front": "F", "back": ""},
        {"front": "x" * 1001, "back": "B"},
        {"front": "F", "back": "x" * 2001},
        {"front": "F"},
        {"back": "B"},
    ],
)
def test_a_card_needs_both_sides_within_their_limits(
    api: TestClient, world: dict[str, Any], body: dict[str, Any]
) -> None:
    response = api.post(
        f"/v1/goals/{world['goal']}/flashcards", headers=world["alice"].headers, json=body
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "extra",
    [
        {"user_id": str(uuid4())},
        {"goal_id": str(uuid4())},
        {"due_at": "2030-01-01T00:00:00Z"},
        {"interval_days": 300},
        {"ease_factor": 3.5},
        {"origin": "manual"},
    ],
)
def test_a_body_cannot_name_an_owner_or_a_schedule(
    api: TestClient, world: dict[str, Any], extra: dict[str, Any]
) -> None:
    response = api.post(
        f"/v1/goals/{world['goal']}/flashcards",
        headers=world["alice"].headers,
        json={**CARD, **extra},
    )

    assert response.status_code == 422


def test_a_card_can_name_a_topic_of_its_own_goal_and_only_that(
    api: TestClient, database_dsn: str, make_learner: MakeLearner
) -> None:
    alice = make_learner()
    goal = create_goal(api, alice)["id"]
    other_goal = create_goal(api, alice, title="Another goal")["id"]
    topics = topic_ids(generate_roadmap(api, database_dsn, alice, goal))
    other_topics = topic_ids(generate_roadmap(api, database_dsn, alice, other_goal))

    assert add_card(api, alice, goal, item_id=topics[0])["item_id"] == topics[0]
    for bad in (str(uuid4()), other_topics[0]):
        response = api.post(
            f"/v1/goals/{goal}/flashcards", headers=alice.headers, json={**CARD, "item_id": bad}
        )
        assert response.status_code == 422, response.text
        assert response.json()["code"] == "UNKNOWN_TOPIC"


def test_someone_elses_topic_is_refused_like_an_unknown_one(
    api: TestClient, database_dsn: str, make_learner: MakeLearner
) -> None:
    alice, bob = make_learner(), make_learner()
    bob_goal = create_goal(api, bob)["id"]
    bob_topic = topic_ids(generate_roadmap(api, database_dsn, bob, bob_goal))[0]
    goal = create_goal(api, alice)["id"]

    response = api.post(
        f"/v1/goals/{goal}/flashcards", headers=alice.headers, json={**CARD, "item_id": bob_topic}
    )

    assert response.status_code == 422
    assert response.json()["code"] == "UNKNOWN_TOPIC"


# --- Ownership ------------------------------------------------------------------------------------


def test_another_learner_gets_404_everywhere(api: TestClient, world: dict[str, Any]) -> None:
    card = add_card(api, world["alice"], world["goal"])
    bob = world["bob"].headers
    card_id, goal_id = card["id"], world["goal"]

    responses = [
        api.post(f"/v1/goals/{goal_id}/flashcards", headers=bob, json=CARD),
        api.get(f"/v1/goals/{goal_id}/flashcards", headers=bob),
        api.get(f"/v1/goals/{goal_id}/flashcards/due", headers=bob),
        api.patch(f"/v1/flashcards/{card_id}", headers=bob, json={"front": "hacked"}),
        api.delete(f"/v1/flashcards/{card_id}", headers=bob),
        api.post(f"/v1/flashcards/{card_id}/reviews", headers=bob, json={"rating": "easy"}),
        api.get(f"/v1/flashcards/{card_id}/reviews", headers=bob),
    ]

    assert [r.status_code for r in responses] == [404] * 7
    # Nothing leaked and nothing changed: the same problem for a missing and a foreign resource.
    missing = api.get(f"/v1/flashcards/{uuid4()}/reviews", headers=bob)
    assert responses[-1].json()["code"] == missing.json()["code"] == "FLASHCARD_NOT_FOUND"
    mine = api.get(f"/v1/goals/{goal_id}/flashcards", headers=world["alice"].headers).json()
    assert mine["cards"][0]["front"] == CARD["front"]
    assert mine["summary"]["reviewed_today"] == 0


def test_a_learner_only_sees_their_own_cards_even_with_the_same_goal_title(
    api: TestClient, world: dict[str, Any]
) -> None:
    add_card(api, world["alice"], world["goal"])
    bobs_goal = create_goal(api, world["bob"])["id"]

    body = api.get(f"/v1/goals/{bobs_goal}/flashcards", headers=world["bob"].headers).json()

    assert body["cards"] == []


# --- The limit and archived goals ----------------------------------------------------------------


def test_a_goal_holds_a_limited_number_of_cards(
    api: TestClient, database_dsn: str, world: dict[str, Any]
) -> None:
    admin(database_dsn).execute(
        "insert into public.flashcards (user_id, goal_id, front, back)"
        " select %s, %s, 'front ' || n, 'back' from generate_series(1, %s) as n",
        (world["alice"].id, world["goal"], MAX_CARDS_PER_GOAL),
    )

    response = api.post(
        f"/v1/goals/{world['goal']}/flashcards", headers=world["alice"].headers, json=CARD
    )

    assert response.status_code == 409
    assert response.json()["code"] == "FLASHCARD_LIMIT_REACHED"


def test_an_archived_goal_is_read_only_but_still_readable(
    api: TestClient, world: dict[str, Any]
) -> None:
    alice, goal = world["alice"], world["goal"]
    card = add_card(api, alice, goal)
    set_status(api, alice, goal, "archived")

    blocked = [
        api.post(f"/v1/goals/{goal}/flashcards", headers=alice.headers, json=CARD),
        api.patch(f"/v1/flashcards/{card['id']}", headers=alice.headers, json={"front": "x"}),
        api.delete(f"/v1/flashcards/{card['id']}", headers=alice.headers),
        review(api, alice, card["id"]),
    ]
    readable = [
        api.get(f"/v1/goals/{goal}/flashcards", headers=alice.headers),
        api.get(f"/v1/goals/{goal}/flashcards/due", headers=alice.headers),
        api.get(f"/v1/flashcards/{card['id']}/reviews", headers=alice.headers),
    ]

    assert [r.status_code for r in blocked] == [409] * 4
    assert {r.json()["code"] for r in blocked} == {"GOAL_ARCHIVED"}
    assert [r.status_code for r in readable] == [200] * 3


# --- Editing and deleting -------------------------------------------------------------------------


def test_a_card_can_be_edited_and_its_schedule_stays_put(
    api: TestClient, world: dict[str, Any]
) -> None:
    alice = world["alice"]
    card = add_card(api, alice, world["goal"])
    reviewed = review(api, alice, card["id"], "good").json()["card"]

    response = api.patch(
        f"/v1/flashcards/{card['id']}", headers=alice.headers, json={"front": "  New front  "}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["front"] == "New front"
    assert body["back"] == CARD["back"]
    assert body["due_at"] == reviewed["due_at"] and body["interval_days"] == 1


def test_a_card_can_be_attached_to_a_topic_and_detached_again(
    api: TestClient, database_dsn: str, make_learner: MakeLearner
) -> None:
    alice = make_learner()
    goal = create_goal(api, alice)["id"]
    topic = topic_ids(generate_roadmap(api, database_dsn, alice, goal))[0]
    card = add_card(api, alice, goal)

    attached = api.patch(
        f"/v1/flashcards/{card['id']}", headers=alice.headers, json={"item_id": topic}
    )
    detached = api.patch(
        f"/v1/flashcards/{card['id']}", headers=alice.headers, json={"item_id": None}
    )
    unknown = api.patch(
        f"/v1/flashcards/{card['id']}", headers=alice.headers, json={"item_id": str(uuid4())}
    )

    assert attached.json()["item_id"] == topic
    assert detached.status_code == 200 and detached.json()["item_id"] is None
    assert unknown.status_code == 422 and unknown.json()["code"] == "UNKNOWN_TOPIC"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"front": None},
        {"back": ""},
        {"due_at": "2030-01-01T00:00:00Z"},
        {"interval_days": 5},
        {"user_id": str(uuid4())},
    ],
)
def test_an_edit_must_change_something_it_may_change(
    api: TestClient, world: dict[str, Any], body: dict[str, Any]
) -> None:
    card = add_card(api, world["alice"], world["goal"])

    response = api.patch(f"/v1/flashcards/{card['id']}", headers=world["alice"].headers, json=body)

    assert response.status_code == 422


def test_deleting_a_card_removes_it_and_its_history(api: TestClient, world: dict[str, Any]) -> None:
    alice = world["alice"]
    card = add_card(api, alice, world["goal"])
    review(api, alice, card["id"])

    assert api.delete(f"/v1/flashcards/{card['id']}", headers=alice.headers).status_code == 204

    assert api.delete(f"/v1/flashcards/{card['id']}", headers=alice.headers).status_code == 404
    assert api.get(f"/v1/flashcards/{card['id']}/reviews", headers=alice.headers).status_code == 404
    deck = api.get(f"/v1/goals/{world['goal']}/flashcards", headers=alice.headers).json()
    assert deck["cards"] == [] and deck["summary"]["reviewed_today"] == 0


# --- Reviewing -------------------------------------------------------------------------------


def test_a_good_review_schedules_the_card_for_tomorrow_and_records_it(
    api: TestClient, world: dict[str, Any]
) -> None:
    alice = world["alice"]
    card = add_card(api, alice, world["goal"])

    response = review(api, alice, card["id"], "good")

    assert response.status_code == 201
    body = response.json()
    updated, record = body["card"], body["review"]
    assert (updated["interval_days"], updated["repetitions"], updated["lapses"]) == (1, 1, 0)
    assert updated["is_due"] is False
    assert updated["last_reviewed_at"] == record["reviewed_at"]
    delta = parse(updated["due_at"]) - parse(record["reviewed_at"])
    assert delta.days == 1 and delta.seconds == 0
    assert record["rating"] == "good"
    assert record["scheduler_version"] == "sm2-v1"
    assert (record["interval_before"], record["interval_after"]) == (0, 1)
    assert (record["ease_before"], record["ease_after"]) == (2.5, 2.5)
    assert record["card_id"] == card["id"]


def test_forgetting_a_card_brings_it_back_within_minutes_and_counts_a_lapse(
    api: TestClient, world: dict[str, Any]
) -> None:
    alice = world["alice"]
    card = add_card(api, alice, world["goal"])

    body = review(api, alice, card["id"], "again").json()

    assert (body["card"]["interval_days"], body["card"]["lapses"]) == (0, 1)
    assert body["card"]["ease_factor"] == 2.3
    minutes = (parse(body["card"]["due_at"]) - parse(body["review"]["reviewed_at"])).seconds / 60
    assert minutes == 10


def test_successive_good_reviews_follow_the_steps_one_six_then_fifteen(
    api: TestClient, database_dsn: str, world: dict[str, Any]
) -> None:
    alice = world["alice"]
    card_id = add_card(api, alice, world["goal"])["id"]
    intervals: list[int] = []
    for _ in range(3):
        intervals.append(review(api, alice, card_id, "good").json()["card"]["interval_days"])
        # Pretend the day has come, so the next review is the next step.
        admin(database_dsn).execute(
            "update public.flashcards set due_at = now() - interval '1 minute' where id = %s",
            (card_id,),
        )

    assert intervals == [1, 6, 15]


def test_a_review_needs_a_known_rating_and_nothing_else(
    api: TestClient, world: dict[str, Any]
) -> None:
    alice = world["alice"]
    card = add_card(api, alice, world["goal"])
    url = f"/v1/flashcards/{card['id']}/reviews"

    for body in (
        {"rating": "perfect"},
        {"rating": 5},
        {},
        {"rating": "good", "interval_days": 999},
    ):
        assert api.post(url, headers=alice.headers, json=body).status_code == 422
    # Nothing was applied by the failed attempts.
    assert api.get(url, headers=alice.headers).json() == {"reviews": []}


def test_the_same_idempotency_key_applies_the_rating_once(
    api: TestClient, world: dict[str, Any]
) -> None:
    alice = world["alice"]
    card = add_card(api, alice, world["goal"])

    first = review(api, alice, card["id"], "good", key="double-click-1")
    again = review(api, alice, card["id"], "good", key="double-click-1")

    assert (first.status_code, again.status_code) == (201, 200)
    assert again.json()["review"]["id"] == first.json()["review"]["id"]
    assert again.json()["card"]["repetitions"] == 1
    history = api.get(f"/v1/flashcards/{card['id']}/reviews", headers=alice.headers).json()
    assert len(history["reviews"]) == 1


def test_a_different_key_is_a_new_review(api: TestClient, world: dict[str, Any]) -> None:
    alice = world["alice"]
    card = add_card(api, alice, world["goal"])

    review(api, alice, card["id"], "good", key="first-review")
    second = review(api, alice, card["id"], "good", key="second-review")

    assert second.status_code == 201
    assert second.json()["card"]["repetitions"] == 2
    history = api.get(f"/v1/flashcards/{card['id']}/reviews", headers=alice.headers).json()
    assert [r["interval_after"] for r in history["reviews"]] == [6, 1]  # newest first


def test_a_malformed_idempotency_key_is_refused(api: TestClient, world: dict[str, Any]) -> None:
    alice = world["alice"]
    card = add_card(api, alice, world["goal"])

    assert review(api, alice, card["id"], "good", key="short").status_code == 422


# --- The due queue --------------------------------------------------------------------------------


def test_the_due_queue_lists_what_is_due_most_overdue_first(
    api: TestClient, database_dsn: str, world: dict[str, Any]
) -> None:
    alice, goal = world["alice"], world["goal"]
    newer = add_card(api, alice, goal, front="Newer")
    older = add_card(api, alice, goal, front="Older")
    later = add_card(api, alice, goal, front="Later")
    for card, overdue_seconds in ((newer, 3600), (older, 3 * 86400)):
        admin(database_dsn).execute(
            "update public.flashcards set due_at = now() - make_interval(secs => %s) where id = %s",
            (overdue_seconds, card["id"]),
        )
    admin(database_dsn).execute(
        "update public.flashcards set due_at = now() + interval '2 days' where id = %s",
        (later["id"],),
    )

    body = api.get(f"/v1/goals/{goal}/flashcards/due", headers=alice.headers).json()

    assert [c["front"] for c in body["cards"]] == ["Older", "Newer"]
    assert all(c["is_due"] for c in body["cards"])
    assert body["summary"]["due_now"] == 2 and body["summary"]["total"] == 3
    assert body["summary"]["next_due_at"] is not None


def test_a_reviewed_card_leaves_the_queue_and_the_batch_is_bounded(
    api: TestClient, world: dict[str, Any]
) -> None:
    alice, goal = world["alice"], world["goal"]
    cards = [add_card(api, alice, goal, front=f"Card {n}") for n in range(3)]
    review(api, alice, cards[0]["id"], "easy")

    body = api.get(f"/v1/goals/{goal}/flashcards/due", headers=alice.headers).json()
    one = api.get(f"/v1/goals/{goal}/flashcards/due?limit=1", headers=alice.headers).json()

    assert {c["id"] for c in body["cards"]} == {cards[1]["id"], cards[2]["id"]}
    assert len(one["cards"]) == 1 and one["summary"]["due_now"] == 2
    for bad in ("0", "51", "abc"):
        assert (
            api.get(
                f"/v1/goals/{goal}/flashcards/due?limit={bad}", headers=alice.headers
            ).status_code
            == 422
        )


def test_an_again_card_comes_back_after_its_minutes_not_at_once(
    api: TestClient, database_dsn: str, world: dict[str, Any]
) -> None:
    alice, goal = world["alice"], world["goal"]
    card = add_card(api, alice, goal)
    review(api, alice, card["id"], "again")

    gone = api.get(f"/v1/goals/{goal}/flashcards/due", headers=alice.headers).json()
    admin(database_dsn).execute(
        "update public.flashcards set due_at = now() - interval '1 second' where id = %s",
        (card["id"],),
    )
    back = api.get(f"/v1/goals/{goal}/flashcards/due", headers=alice.headers).json()

    assert gone["cards"] == [] and [c["id"] for c in back["cards"]] == [card["id"]]
