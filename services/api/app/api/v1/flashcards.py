from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Header, Query, Response

from app.api.deps import DatabaseDep
from app.core.errors import ProblemDetail
from app.core.security import CurrentPrincipal
from app.schemas.flashcards import (
    DEFAULT_DUE_BATCH,
    MAX_DUE_BATCH,
    Flashcard,
    FlashcardCreate,
    FlashcardDueQueue,
    FlashcardList,
    FlashcardReviewHistory,
    FlashcardReviewRequest,
    FlashcardReviewResult,
    FlashcardUpdate,
)
from app.services import flashcards as flashcards_service

router = APIRouter(tags=["flashcards"])

_NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {"model": ProblemDetail, "description": "No such goal or flashcard for this user"}
}
_CONFLICT: dict[int | str, dict[str, Any]] = {
    409: {"model": ProblemDetail, "description": "The goal is archived or the limit is reached"}
}

IdempotencyKey = Annotated[
    str | None,
    Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=128,
        description="Send the same value when resubmitting a review: it is applied only once.",
    ),
]


@router.post(
    "/goals/{goal_id}/flashcards",
    response_model=Flashcard,
    status_code=201,
    summary="Add a flashcard to a goal",
    responses={**_NOT_FOUND, **_CONFLICT, 422: {"model": ProblemDetail}},
)
async def create_flashcard(
    goal_id: UUID, payload: FlashcardCreate, principal: CurrentPrincipal, database: DatabaseDep
) -> Flashcard:
    """The card is due at once. It may name a topic of the goal's roadmap (422 `UNKNOWN_TOPIC`
    otherwise). A goal holds a limited number of cards (409 `FLASHCARD_LIMIT_REACHED`)."""
    async with database.user_transaction(principal) as connection:
        return await flashcards_service.create_card(connection, principal, goal_id, payload)


@router.get(
    "/goals/{goal_id}/flashcards",
    response_model=FlashcardList,
    summary="A goal's flashcards, newest first, with where the deck stands",
    responses=_NOT_FOUND,
)
async def list_flashcards(
    goal_id: UUID, principal: CurrentPrincipal, database: DatabaseDep
) -> FlashcardList:
    async with database.user_transaction(principal) as connection:
        return await flashcards_service.list_cards(connection, principal, goal_id)


@router.get(
    "/goals/{goal_id}/flashcards/due",
    response_model=FlashcardDueQueue,
    summary="The cards to review now, most overdue first",
    responses=_NOT_FOUND,
)
async def due_flashcards(
    goal_id: UUID,
    principal: CurrentPrincipal,
    database: DatabaseDep,
    limit: Annotated[int, Query(ge=1, le=MAX_DUE_BATCH)] = DEFAULT_DUE_BATCH,
) -> FlashcardDueQueue:
    async with database.user_transaction(principal) as connection:
        return await flashcards_service.due_queue(connection, principal, goal_id, limit=limit)


@router.patch(
    "/flashcards/{card_id}",
    response_model=Flashcard,
    summary="Change what a card says or which topic it is about",
    responses={**_NOT_FOUND, **_CONFLICT, 422: {"model": ProblemDetail}},
)
async def update_flashcard(
    card_id: UUID, payload: FlashcardUpdate, principal: CurrentPrincipal, database: DatabaseDep
) -> Flashcard:
    """The schedule is not editable: it only moves when the card is reviewed."""
    async with database.user_transaction(principal) as connection:
        return await flashcards_service.update_card(connection, principal, card_id, payload)


@router.delete(
    "/flashcards/{card_id}",
    status_code=204,
    summary="Delete a card and its review history",
    responses={**_NOT_FOUND, **_CONFLICT},
)
async def delete_flashcard(
    card_id: UUID, principal: CurrentPrincipal, database: DatabaseDep
) -> Response:
    async with database.user_transaction(principal) as connection:
        await flashcards_service.delete_card(connection, principal, card_id)
    return Response(status_code=204)


@router.post(
    "/flashcards/{card_id}/reviews",
    response_model=FlashcardReviewResult,
    status_code=201,
    summary="Rate how well you remembered a card",
    responses={
        **_NOT_FOUND,
        **_CONFLICT,
        200: {
            "model": FlashcardReviewResult,
            "description": "The same review again: the same result",
        },
        422: {"model": ProblemDetail},
    },
)
async def review_flashcard(
    card_id: UUID,
    payload: FlashcardReviewRequest,
    response: Response,
    principal: CurrentPrincipal,
    database: DatabaseDep,
    idempotency_key: IdempotencyKey = None,
) -> FlashcardReviewResult:
    """The server decides the card's next due date from the rating (`again`, `hard`, `good`,
    `easy`) and records the review. Send an `Idempotency-Key` so a double click counts once."""
    async with database.user_transaction(principal) as connection:
        result, created = await flashcards_service.review_card(
            connection, principal, card_id, payload.rating, idempotency_key=idempotency_key
        )
    if not created:
        response.status_code = 200
    return result


@router.get(
    "/flashcards/{card_id}/reviews",
    response_model=FlashcardReviewHistory,
    summary="A card's review history, newest first",
    responses=_NOT_FOUND,
)
async def flashcard_history(
    card_id: UUID, principal: CurrentPrincipal, database: DatabaseDep
) -> FlashcardReviewHistory:
    async with database.user_transaction(principal) as connection:
        return await flashcards_service.card_history(connection, principal, card_id)
