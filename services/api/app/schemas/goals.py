"""Request and response contracts for learning goals.

Requests reject unknown fields (``extra="forbid"``), so a client that sends ``user_id`` (or any
other field the server owns) gets a validation error instead of being silently ignored.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

GoalType = Literal[
    "exam", "academic_subject", "professional_skill", "certification", "interview", "general"
]
GoalLevel = Literal["unknown", "beginner", "intermediate", "advanced"]
GoalStatus = Literal["active", "paused", "completed", "archived"]

# Languages learners can currently choose for study material. Adding one is a code change only
# (the database enforces just the shape of a language code).
SUPPORTED_LANGUAGES: tuple[str, ...] = ("en", "hi", "or")

MIN_DAILY_MINUTES = 10
MAX_DAILY_MINUTES = 480
_MAX_TARGET_DATE_YEARS = 5


def today_utc() -> date:
    return datetime.now(UTC).date()


class GoalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    description: Annotated[str, StringConstraints(max_length=2000)] | None = None
    goal_type: GoalType = "general"
    current_level: GoalLevel = "unknown"
    target_date: date | None = None
    daily_minutes: int = Field(default=60, ge=MIN_DAILY_MINUTES, le=MAX_DAILY_MINUTES)
    preferred_languages: list[str] = Field(
        default_factory=lambda: ["en"], min_length=1, max_length=5
    )

    @field_validator("description")
    @classmethod
    def _blank_description_is_none(cls, value: str | None) -> str | None:
        return value or None

    @field_validator("target_date")
    @classmethod
    def _target_date_is_plausible(cls, value: date | None) -> date | None:
        if value is None:
            return None
        today = today_utc()
        # One day of grace so a learner ahead of UTC can still pick "today".
        if value < today - timedelta(days=1):
            raise ValueError("The target date can't be in the past.")
        if value > today + timedelta(days=365 * _MAX_TARGET_DATE_YEARS):
            raise ValueError(f"The target date must be within {_MAX_TARGET_DATE_YEARS} years.")
        return value

    @field_validator("preferred_languages")
    @classmethod
    def _languages_are_supported(cls, value: list[str]) -> list[str]:
        unsupported = [code for code in value if code not in SUPPORTED_LANGUAGES]
        if unsupported:
            raise ValueError(f"Choose from: {', '.join(SUPPORTED_LANGUAGES)}.")
        return list(dict.fromkeys(value))  # drop duplicates, keep order


class Goal(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    description: str | None
    goal_type: GoalType
    current_level: GoalLevel
    target_date: date | None
    daily_minutes: int
    preferred_languages: list[str]
    status: GoalStatus
    created_at: datetime
    updated_at: datetime


class GoalPage(BaseModel):
    items: list[Goal]
    # Opaque. Pass it back as ?cursor= to get the next page; null on the last page.
    next_cursor: str | None
