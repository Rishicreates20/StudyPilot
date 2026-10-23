"""Business rules for flashcards: whose they are, when they are due, and what a review does.

A learner writes their own cards and rates how well they remembered each one; the server alone
decides the new schedule, with the pure scheduler in ``app.learning.scheduling``, and records every
review (the schedule before and after, and the scheduler's version) so the method can be replaced
and old history replayed (ADR-050). No model is involved. Logs carry identifiers and counts, never
what a card says.
"""

from uuid import UUID

import structlog

from app.core.db import UserConnection
from app.core.errors import ConflictError, InvalidRequestError, NotFoundError
from app.core.security import Principal
from app.learning.scheduling import SCHEDULER_VERSION, CardSchedule, Rating, schedule_review
from app.repositories import flashcards as cards_repo
from app.repositories import goals as goals_repo
from app.schemas.flashcards import (
    DEFAULT_DUE_BATCH,
    MAX_CARDS_PER_GOAL,
    Flashcard,
    FlashcardCreate,
    FlashcardDueQueue,
    FlashcardList,
    FlashcardReviewHistory,
    FlashcardReviewResult,
    FlashcardUpdate,
)

log = structlog.get_logger("app.flashcards")

_HISTORY_LIMIT = 100


def _goal_not_found() -> NotFoundError:
    return NotFoundError("Goal not found.", code="GOAL_NOT_FOUND")


def _card_not_found() -> NotFoundError:
    # The same answer for "does not exist" and "belongs to someone else".
    return NotFoundError("Flashcard not found.", code="FLASHCARD_NOT_FOUND")


def _archived() -> ConflictError:
    return ConflictError(
        "This goal is archived. Restore it to work with its flashcards.", code="GOAL_ARCHIVED"
    )


async def _require_topic(
    connection: UserConnection, principal: Principal, goal_id: UUID, item_id: UUID
) -> None:
    if not await cards_repo.topic_belongs_to_goal(connection, principal.user_id, goal_id, item_id):
        raise InvalidRequestError(
            "That topic is not part of this goal's roadmap.", code="UNKNOWN_TOPIC"
        )


async def _own_card(
    connection: UserConnection, principal: Principal, card_id: UUID, *, for_update: bool = False
) -> Flashcard:
    card = await cards_repo.get(connection, principal.user_id, card_id, for_update=for_update)
    if card is None:
        raise _card_not_found()
    return card


async def _require_writable_goal(
    connection: UserConnection, principal: Principal, goal_id: UUID
) -> None:
    goal = await goals_repo.get(connection, principal.user_id, goal_id)
    if goal is None:
        raise _goal_not_found()
    if goal.status == "archived":
        raise _archived()


async def create_card(
    connection: UserConnection, principal: Principal, goal_id: UUID, payload: FlashcardCreate
) -> Flashcard:
    # Locking the goal makes the limit check and the insert one step, so two requests at once
    # cannot both slip under the limit.
    goal = await goals_repo.get(connection, principal.user_id, goal_id, for_update=True)
    if goal is None:
        raise _goal_not_found()
    if goal.status == "archived":
        raise _archived()
    if payload.item_id is not None:
        await _require_topic(connection, principal, goal_id, payload.item_id)
    if (
        await cards_repo.count_for_goal(connection, principal.user_id, goal_id)
        >= MAX_CARDS_PER_GOAL
    ):
        raise ConflictError(
            f"A goal can have at most {MAX_CARDS_PER_GOAL} flashcards. Delete some to add more.",
            code="FLASHCARD_LIMIT_REACHED",
        )
    card = await cards_repo.insert(
        connection,
        principal.user_id,
        goal_id,
        front=payload.front,
        back=payload.back,
        item_id=payload.item_id,
    )
    log.info("flashcard.created", card_id=str(card.id), goal_id=str(goal_id))
    return card


async def list_cards(
    connection: UserConnection, principal: Principal, goal_id: UUID
) -> FlashcardList:
    """Every card of a goal (reading is allowed on archived goals), newest first."""
    if await goals_repo.get(connection, principal.user_id, goal_id) is None:
        raise _goal_not_found()
    cards = await cards_repo.list_for_goal(
        connection, principal.user_id, goal_id, limit=MAX_CARDS_PER_GOAL
    )
    summary = await cards_repo.summary(connection, principal.user_id, goal_id)
    return FlashcardList(cards=cards, summary=summary)


async def due_queue(
    connection: UserConnection,
    principal: Principal,
    goal_id: UUID,
    *,
    limit: int = DEFAULT_DUE_BATCH,
) -> FlashcardDueQueue:
    if await goals_repo.get(connection, principal.user_id, goal_id) is None:
        raise _goal_not_found()
    cards = await cards_repo.due_for_goal(connection, principal.user_id, goal_id, limit=limit)
    summary = await cards_repo.summary(connection, principal.user_id, goal_id)
    return FlashcardDueQueue(cards=cards, summary=summary)


async def update_card(
    connection: UserConnection, principal: Principal, card_id: UUID, payload: FlashcardUpdate
) -> Flashcard:
    card = await _own_card(connection, principal, card_id)
    await _require_writable_goal(connection, principal, card.goal_id)
    set_item = "item_id" in payload.model_fields_set
    if set_item and payload.item_id is not None:
        await _require_topic(connection, principal, card.goal_id, payload.item_id)
    updated = await cards_repo.update_text(
        connection,
        principal.user_id,
        card_id,
        front=payload.front,
        back=payload.back,
        set_item=set_item,
        item_id=payload.item_id,
    )
    if updated is None:
        raise _card_not_found()
    return updated


async def delete_card(connection: UserConnection, principal: Principal, card_id: UUID) -> None:
    card = await _own_card(connection, principal, card_id)
    await _require_writable_goal(connection, principal, card.goal_id)
    if not await cards_repo.delete(connection, principal.user_id, card_id):
        raise _card_not_found()
    log.info("flashcard.deleted", card_id=str(card_id))


async def review_card(
    connection: UserConnection,
    principal: Principal,
    card_id: UUID,
    rating: Rating,
    *,
    idempotency_key: str | None,
) -> tuple[FlashcardReviewResult, bool]:
    """Record a review and move the card's schedule. Returns the result and whether it is new.

    The card is locked first, so two reviews of one card queue up instead of both starting from the
    same schedule, and a repeat with the same ``Idempotency-Key`` (a double submit) returns the
    review that was already made instead of applying the rating twice.
    """
    card = await _own_card(connection, principal, card_id, for_update=True)
    await _require_writable_goal(connection, principal, card.goal_id)

    if idempotency_key is not None:
        earlier = await cards_repo.find_review_by_key(
            connection, principal.user_id, card_id, idempotency_key
        )
        if earlier is not None:
            return FlashcardReviewResult(card=card, review=earlier), False

    now = await cards_repo.database_now(connection)
    scheduled = schedule_review(
        CardSchedule(
            interval_days=card.interval_days,
            ease_factor=card.ease_factor,
            repetitions=card.repetitions,
            lapses=card.lapses,
        ),
        rating,
        now,
    )
    updated = await cards_repo.apply_schedule(
        connection,
        principal.user_id,
        card_id,
        scheduled,
        reviewed_at=now,
        scheduler_version=SCHEDULER_VERSION,
    )
    review = await cards_repo.insert_review(
        connection,
        principal.user_id,
        card_id,
        rating=rating,
        scheduler_version=SCHEDULER_VERSION,
        interval_before=card.interval_days,
        ease_before=card.ease_factor,
        scheduled=scheduled,
        idempotency_key=idempotency_key,
    )
    log.info(
        "flashcard.reviewed",
        card_id=str(card_id),
        rating=rating,
        interval_days=scheduled.interval_days,
        lapses=scheduled.lapses,
    )
    return FlashcardReviewResult(card=updated, review=review), True


async def card_history(
    connection: UserConnection, principal: Principal, card_id: UUID
) -> FlashcardReviewHistory:
    await _own_card(connection, principal, card_id)
    reviews = await cards_repo.list_reviews(
        connection, principal.user_id, card_id, limit=_HISTORY_LIMIT
    )
    return FlashcardReviewHistory(reviews=reviews)
