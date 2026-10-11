"""Request and response contracts for learning goals.

Requests reject unknown fields (``extra="forbid"``), so a client that sends ``user_id`` (or any
other field the server owns, such as ``status`` on create or ``completed_at``) gets a validation
error instead of being silently ignored.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

GoalType = Literal[
    "exam", "academic_subject", "professional_skill", "certification", "interview", "general"
]
GoalLevel = Literal["unknown", "beginner", "intermediate", "advanced"]
GoalStatus = Literal["active", "paused", "completed", "archived"]
LearningPreference = Literal["examples", "quizzes", "revision"]

# Languages learners can currently choose for study material. Adding one is a code change only
# (the database enforces just the shape of a language code).
SUPPORTED_LANGUAGES: tuple[str, ...] = ("en", "hi", "or")
LEARNING_PREFERENCES: tuple[LearningPreference, ...] = ("examples", "quizzes", "revision")

MIN_DAILY_MINUTES = 10
MAX_DAILY_MINUTES = 480
DEFAULT_DAILY_MINUTES = 60
_MAX_TARGET_DATE_YEARS = 5

Title = Annotated[str, StringConstraints(min_length=1, max_length=200)]
Description = Annotated[str, StringConstraints(max_length=2000)]
DailyMinutes = Annotated[int, Field(ge=MIN_DAILY_MINUTES, le=MAX_DAILY_MINUTES)]
Languages = Annotated[list[str], Field(min_length=1, max_length=5)]
LearningPreferences = Annotated[list[LearningPreference], Field(max_length=3)]


def today_utc() -> date:
    return datetime.now(UTC).date()


def check_target_date(value: date) -> str | None:
    """Why ``value`` is not an acceptable target date, or None if it is fine."""
    today = today_utc()
    # One day of grace so a learner ahead of UTC can still pick "today".
    if value < today - timedelta(days=1):
        return "The target date can't be in the past."
    if value > today + timedelta(days=365 * _MAX_TARGET_DATE_YEARS):
        return f"The target date must be within {_MAX_TARGET_DATE_YEARS} years."
    return None


def check_languages(value: list[str]) -> list[str]:
    unsupported = [code for code in value if code not in SUPPORTED_LANGUAGES]
    if unsupported:
        raise ValueError(f"Choose from: {', '.join(SUPPORTED_LANGUAGES)}.")
    return list(dict.fromkeys(value))  # drop duplicates, keep order


class _GoalInput(BaseModel):
    """Rules shared by creating and editing a goal."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @field_validator("description", check_fields=False)
    @classmethod
    def _blank_description_is_none(cls, value: str | None) -> str | None:
        return value or None

    @field_validator("preferred_languages", check_fields=False)
    @classmethod
    def _languages_are_supported(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else check_languages(value)

    @field_validator("learning_preferences", check_fields=False)
    @classmethod
    def _preferences_are_unique(
        cls, value: list[LearningPreference] | None
    ) -> list[LearningPreference] | None:
        return None if value is None else list(dict.fromkeys(value))


class GoalCreate(_GoalInput):
    """A new goal. Omitted settings fall back to the learner's saved preferences."""

    title: Title
    description: Description | None = None
    goal_type: GoalType = "general"
    current_level: GoalLevel = "unknown"
    target_date: date | None = None
    daily_minutes: DailyMinutes | None = None
    preferred_languages: Languages | None = None
    learning_preferences: LearningPreferences | None = None

    @field_validator("target_date")
    @classmethod
    def _target_date_is_plausible(cls, value: date | None) -> date | None:
        if value is not None and (problem := check_target_date(value)):
            raise ValueError(problem)
        return value


class GoalUpdate(_GoalInput):
    """Changes to a goal. Send only the fields to change; ``null`` clears an optional field.

    The target date is checked against today only when it actually changes (see the service), so
    a goal whose date has passed can still be renamed.
    """

    title: Title | None = None
    description: Description | None = None
    goal_type: GoalType | None = None
    current_level: GoalLevel | None = None
    target_date: date | None = None
    daily_minutes: DailyMinutes | None = None
    preferred_languages: Languages | None = None
    learning_preferences: LearningPreferences | None = None

    @field_validator(
        "title",
        "goal_type",
        "current_level",
        "daily_minutes",
        "preferred_languages",
        "learning_preferences",
    )
    @classmethod
    def _required_fields_cannot_be_cleared(cls, value: Any) -> Any:
        # Runs only when the field is present in the body (defaults are not validated), so an
        # explicit null is the only way to get here with None.
        if value is None:
            raise ValueError("This can't be cleared. Send a value or leave the field out.")
        return value

    @model_validator(mode="after")
    def _something_must_change(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("Send at least one field to change.")
        return self

    def changes(self) -> dict[str, Any]:
        """The fields the client sent (including explicit nulls), keyed by column name."""
        return {name: getattr(self, name) for name in self.model_fields_set}


class GoalStatusChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: GoalStatus


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
    learning_preferences: list[LearningPreference]
    status: GoalStatus
    completed_at: datetime | None
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class GoalPage(BaseModel):
    items: list[Goal]
    # Opaque. Pass it back as ?cursor= to get the next page; null on the last page.
    next_cursor: str | None


class GoalSummary(BaseModel):
    """How many goals the caller has in each state."""

    active: int
    paused: int
    completed: int
    archived: int
