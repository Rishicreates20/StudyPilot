"""Request and response contracts for flashcards, their reviews and the due queue (ADR-050).

Requests reject unknown fields (``extra="forbid"``): a body that names an owner, a schedule or a due
date is a validation error, because the server alone decides those. The learner supplies the two
sides of a card, optionally the roadmap topic it is about, and later a rating.
"""

from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.learning.scheduling import Rating

MAX_FRONT_CHARS = 1000
MAX_BACK_CHARS = 2000
MAX_CARDS_PER_GOAL = 500
MAX_DUE_BATCH = 50
DEFAULT_DUE_BATCH = 20

Front = Annotated[str, StringConstraints(min_length=1, max_length=MAX_FRONT_CHARS)]
Back = Annotated[str, StringConstraints(min_length=1, max_length=MAX_BACK_CHARS)]
CardOrigin = Literal["manual"]


class FlashcardCreate(BaseModel):
    """A new card. It is due at once."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    front: Front = Field(description="The question or prompt.")
    back: Back = Field(description="The answer.")
    item_id: UUID | None = Field(
        default=None, description="A topic of this goal's roadmap the card is about (optional)."
    )


class FlashcardUpdate(BaseModel):
    """Change what a card says or which topic it is about. The schedule is not editable here."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    front: Front | None = None
    back: Back | None = None
    # Send `null` to detach the card from its topic; leave the field out to keep it.
    item_id: UUID | None = None

    @model_validator(mode="after")
    def _something_to_change(self) -> Self:
        if not self.model_fields_set & {"front", "back", "item_id"}:
            raise ValueError("send at least one of front, back or item_id")
        if "front" in self.model_fields_set and self.front is None:
            raise ValueError("front cannot be empty")
        if "back" in self.model_fields_set and self.back is None:
            raise ValueError("back cannot be empty")
        return self


class Flashcard(BaseModel):
    id: UUID
    goal_id: UUID
    item_id: UUID | None
    origin: CardOrigin
    front: str
    back: str
    # When it should next be shown, and whether that time has come (decided by the database clock).
    due_at: datetime
    is_due: bool
    interval_days: int
    ease_factor: float
    repetitions: int
    lapses: int
    last_reviewed_at: datetime | None
    scheduler_version: str
    created_at: datetime
    updated_at: datetime


class FlashcardSummary(BaseModel):
    """Where a goal's deck stands."""

    total: int
    due_now: int
    # The earliest time a card that is not due yet will be; null when nothing is waiting.
    next_due_at: datetime | None
    # Reviews done since the start of today (UTC), a gentle sign of consistency, never a target.
    reviewed_today: int
    limit: int = MAX_CARDS_PER_GOAL


class FlashcardList(BaseModel):
    cards: list[Flashcard]
    summary: FlashcardSummary


class FlashcardDueQueue(BaseModel):
    """The cards to review now, most overdue first, and how many more are waiting."""

    cards: list[Flashcard]
    summary: FlashcardSummary


class FlashcardReviewRequest(BaseModel):
    """How well the learner remembered a card."""

    model_config = ConfigDict(extra="forbid")

    rating: Rating = Field(
        description="`again` (forgot), `hard`, `good` or `easy`. The server decides what happens."
    )


class FlashcardReview(BaseModel):
    id: UUID
    card_id: UUID
    rating: Rating
    scheduler_version: str
    reviewed_at: datetime
    interval_before: int
    ease_before: float
    interval_after: int
    ease_after: float
    due_after: datetime


class FlashcardReviewResult(BaseModel):
    """The card with its new schedule, and the review that made it."""

    card: Flashcard
    review: FlashcardReview


class FlashcardReviewHistory(BaseModel):
    reviews: list[FlashcardReview]
