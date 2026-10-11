from datetime import datetime
from functools import lru_cache
from typing import Annotated, Any, Self
from uuid import UUID
from zoneinfo import available_timezones

from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator, model_validator

from app.schemas.goals import (
    SUPPORTED_LANGUAGES,
    DailyMinutes,
    Languages,
    LearningPreference,
    LearningPreferences,
    check_languages,
)

DisplayName = Annotated[str, StringConstraints(min_length=1, max_length=80)]


@lru_cache
def _known_timezones() -> frozenset[str]:
    return frozenset(available_timezones())


class Preferences(BaseModel):
    """Saved choices that pre-fill new goals. Each goal can still override them."""

    default_daily_minutes: int
    preferred_languages: list[str]
    learning_preferences: list[LearningPreference]


class Me(BaseModel):
    """The signed-in user. ``email`` comes from the verified token; the rest from ``profiles``."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str | None
    display_name: str | None
    locale: str
    timezone: str
    onboarding_completed: bool
    preferences: Preferences
    created_at: datetime


class MeUpdate(BaseModel):
    """Changes to the caller's profile and preferences. Send only what changes."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    display_name: DisplayName | None = None
    locale: str | None = None
    timezone: str | None = None
    default_daily_minutes: DailyMinutes | None = None
    preferred_languages: Languages | None = None
    learning_preferences: LearningPreferences | None = None

    @field_validator("display_name", mode="before")
    @classmethod
    def _blank_name_clears_it(cls, value: Any) -> Any:
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("locale")
    @classmethod
    def _locale_is_supported(cls, value: str | None) -> str | None:
        if value is not None and value not in SUPPORTED_LANGUAGES:
            raise ValueError(f"Choose from: {', '.join(SUPPORTED_LANGUAGES)}.")
        return value

    @field_validator("timezone")
    @classmethod
    def _timezone_is_known(cls, value: str | None) -> str | None:
        if value is not None and value not in _known_timezones():
            raise ValueError("Choose a timezone from the list, for example Asia/Kolkata.")
        return value

    @field_validator("preferred_languages")
    @classmethod
    def _languages_are_supported(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else check_languages(value)

    @field_validator("learning_preferences")
    @classmethod
    def _preferences_are_unique(
        cls, value: list[LearningPreference] | None
    ) -> list[LearningPreference] | None:
        return None if value is None else list(dict.fromkeys(value))

    @field_validator(
        "locale",
        "timezone",
        "default_daily_minutes",
        "preferred_languages",
        "learning_preferences",
    )
    @classmethod
    def _required_settings_cannot_be_cleared(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("This can't be cleared. Send a value or leave the field out.")
        return value

    @model_validator(mode="after")
    def _something_must_change(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("Send at least one field to change.")
        return self

    def changes(self) -> dict[str, Any]:
        """The fields the client sent (including an explicit null name), keyed by column name."""
        return {name: getattr(self, name) for name in self.model_fields_set}


class ProfileRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    display_name: str | None
    locale: str
    timezone: str
    onboarding_completed_at: datetime | None
    default_daily_minutes: int
    preferred_languages: list[str]
    learning_preferences: list[LearningPreference]
    created_at: datetime
