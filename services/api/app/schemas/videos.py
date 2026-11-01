"""Request and response contracts for a topic's study videos (ADR-051).

Every video and every fact about it comes from the YouTube Data API; none is written by a model.
The score is a match estimate from YouTube's metadata, not a quality rating, and ``score_basis``
says what it was built from. A video's ``url`` is always the watch address of its ``video_id``.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.jobs import GenerationJob


class VideoSearchRequest(BaseModel):
    """Find videos for a topic, or find them again."""

    model_config = ConfigDict(extra="forbid")

    refresh: bool = Field(
        default=False,
        description=(
            "Search again although the topic already has suggestions. The new results replace "
            "them when the search finishes."
        ),
    )


class TopicVideo(BaseModel):
    id: UUID
    # YouTube's own id for the video (11 characters).
    video_id: str
    # Always https://www.youtube.com/watch?v=<video_id>.
    url: str
    title: str
    channel_title: str
    duration_seconds: int | None
    published_at: datetime | None
    # The language the video declares (a BCP-47 tag), and which of its fields said so.
    language: str | None
    language_source: Literal["audio", "metadata", "unknown"]
    # The language searched for when it was found.
    searched_language: str
    thumbnail_url: str | None
    thumbnail_width: int | None
    thumbnail_height: int | None
    view_count: int | None
    # A match estimate from the metadata (0..100), not a quality rating.
    relevance_score: int = Field(ge=0, le=100)
    score_basis: dict[str, int]
    position: int
    # When YouTube last confirmed these details.
    last_verified_at: datetime


class VideoSearchInfo(BaseModel):
    """The search behind a topic's suggestions: what was asked, and what came back."""

    id: UUID
    queries: list[str]
    languages: list[str]
    candidates_seen: int
    result_count: int
    searched_at: datetime
    last_verified_at: datetime


class TopicVideos(BaseModel):
    """A topic's suggested videos, the search they came from, and the newest search job."""

    item_id: UUID
    # Whether this server can search YouTube at all (a key is configured).
    configured: bool
    # Whether a search can be started now: configured, the current roadmap, goal not archived.
    can_search: bool
    search: VideoSearchInfo | None
    videos: list[TopicVideo]
    # The newest video search for this topic (running now, or the last failure).
    job: GenerationJob | None
