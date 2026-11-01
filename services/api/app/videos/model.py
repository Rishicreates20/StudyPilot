"""Study videos as this app sees them: what YouTube said about a video, and how it was ranked.

Everything here comes from the YouTube Data API's own fields. Nothing is written by a model, and a
video's address is always built from its id (``watch_url``), never taken from a response.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

LanguageSource = Literal["audio", "metadata", "unknown"]

# A YouTube video id: 11 URL-safe characters. The database checks the same shape.
VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")


def watch_url(video_id: str) -> str:
    """The watch address of a video id; the only kind of link this app stores or shows."""
    if not VIDEO_ID.fullmatch(video_id):
        raise ValueError("not a YouTube video id")
    return f"https://www.youtube.com/watch?v={video_id}"


@dataclass(frozen=True)
class VideoDetails:
    """One video as ``videos.list`` describes it."""

    video_id: str
    title: str
    description: str
    channel_id: str | None
    channel_title: str
    published_at: datetime | None
    # None when YouTube gives no usable length (live streams report none).
    duration_seconds: int | None
    category_id: str | None
    # The language the video declares, and which field said so (audio first, then metadata).
    language: str | None
    language_source: LanguageSource
    thumbnail_url: str | None
    thumbnail_width: int | None
    thumbnail_height: int | None
    view_count: int | None
    # Public and fully processed: anyone with the link can watch it.
    watchable: bool
    # A live stream or a scheduled one (no fixed recording to study from).
    live: bool


@dataclass(frozen=True)
class RankedVideo:
    """A video kept for a topic, with the match estimate and what it was built from."""

    details: VideoDetails
    # The language searched for when this video was found.
    searched_language: str
    relevance_score: int
    score_basis: dict[str, int] = field(default_factory=dict[str, int])
    position: int = 1


@dataclass(frozen=True)
class SearchOutcome:
    """What one topic's search found, ready to store."""

    languages: tuple[str, ...]
    queries: tuple[str, ...]
    candidates_seen: int
    units_spent: int
    videos: tuple[RankedVideo, ...]
