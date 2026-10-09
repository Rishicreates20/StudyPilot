from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class Me(BaseModel):
    """The signed-in user. ``email`` comes from the verified token; the rest from ``profiles``."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str | None
    display_name: str | None
    locale: str
    timezone: str
    created_at: datetime


class ProfileRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    display_name: str | None
    locale: str
    timezone: str
    created_at: datetime
