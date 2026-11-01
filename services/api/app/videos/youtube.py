"""The YouTube Data API v3, read-only: find videos for a query, then look up their details.

Two calls are used. ``search.list`` (100 quota units) returns video ids in YouTube's own order;
``videos.list`` (1 unit for up to 50 ids) returns what is shown and checked: title, channel,
length, language, privacy and processing state, category and view count. Search snippets are not
used for display because their text arrives HTML-escaped and they say nothing about length or
privacy.

The key travels in the ``x-goog-api-key`` header, never in the URL, so it cannot end up in an
access log. **[verify]** that header against the live API before relying on it in production.

Errors are mapped to stable codes with a learner-safe message; the provider's own text is kept
for server logs (``detail``) and never shown to anyone.
"""

import re
from collections.abc import Sequence
from datetime import datetime
from typing import Any, cast

import httpx2
from pydantic import SecretStr

from app.videos.model import VIDEO_ID, LanguageSource, VideoDetails

SEARCH_UNITS = 100
DETAILS_UNITS = 1
# videos.list accepts at most 50 ids per call.
DETAILS_BATCH = 50

_MAX_DETAIL_CHARS = 300
_MAX_TITLE_CHARS = 300
_MAX_DESCRIPTION_CHARS = 1000
_MAX_CHANNEL_CHARS = 200
_DURATION = re.compile(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?")
_LANGUAGE = re.compile(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{1,8})*")
_THUMBNAIL = re.compile(r"https://[A-Za-z0-9.-]+/\S*")

_QUOTA_REASONS = frozenset({"quotaExceeded", "dailyLimitExceeded"})
_BUSY_REASONS = frozenset({"rateLimitExceeded", "userRateLimitExceeded"})
_KEY_REASONS = frozenset(
    {
        "keyInvalid",
        "keyExpired",
        "forbidden",
        "accessNotConfigured",
        "ipRefererBlocked",
        "API_KEY_INVALID",
        "API_KEY_SERVICE_BLOCKED",
        "SERVICE_DISABLED",
    }
)


class YouTubeError(Exception):
    """A failed call, with a stable code, a learner-safe message and log-only detail."""

    def __init__(self, code: str, message: str, *, retryable: bool, detail: str) -> None:
        super().__init__(code)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.detail = detail


class YouTubeClient:
    def __init__(
        self,
        client: httpx2.AsyncClient,
        *,
        api_key: SecretStr,
        base_url: str,
        timeout_seconds: float,
    ) -> None:
        self._client = client
        self._api_key = api_key
        self._base = base_url.rstrip("/")
        self._timeout = timeout_seconds

    async def search(self, query: str, *, language: str, max_results: int) -> list[str]:
        """Video ids for ``query``, in YouTube's order, biased toward ``language``."""
        payload = await self._get(
            "search",
            {
                "part": "snippet",
                "type": "video",
                "q": query,
                "maxResults": str(max(1, min(50, max_results))),
                "relevanceLanguage": language,
                "safeSearch": "strict",
                "fields": "items(id(videoId))",
            },
        )
        ids: list[str] = []
        for item in _list(payload.get("items")):
            video_id = _dict(_dict(item).get("id")).get("videoId")
            if isinstance(video_id, str) and VIDEO_ID.fullmatch(video_id) and video_id not in ids:
                ids.append(video_id)
        return ids

    async def videos(self, video_ids: Sequence[str]) -> list[VideoDetails]:
        """Details of up to 50 videos. Ids YouTube no longer knows are simply absent."""
        wanted = [v for v in dict.fromkeys(video_ids) if VIDEO_ID.fullmatch(v)][:DETAILS_BATCH]
        if not wanted:
            return []
        payload = await self._get(
            "videos",
            {
                "part": "snippet,contentDetails,status,statistics",
                "id": ",".join(wanted),
                "maxResults": str(len(wanted)),
            },
        )
        found: list[VideoDetails] = []
        for item in _list(payload.get("items")):
            details = parse_video(_dict(item))
            if details is not None and details.video_id in wanted:
                found.append(details)
        return found

    async def _get(self, endpoint: str, params: dict[str, str]) -> dict[str, Any]:
        try:
            response = await self._client.get(
                f"{self._base}/{endpoint}",
                params=params,
                headers={"x-goog-api-key": self._api_key.get_secret_value()},
                timeout=self._timeout,
            )
        except httpx2.TimeoutException:
            raise _unavailable("request timed out") from None
        except httpx2.TransportError as exc:
            # The exception type is enough to diagnose; its message can include the host.
            raise _unavailable(f"transport error: {type(exc).__name__}") from None
        if not response.is_success:
            raise classify_error(response)
        try:
            payload: object = response.json()
        except ValueError:
            raise _unavailable("the reply was not JSON") from None
        if not isinstance(payload, dict):
            raise _unavailable("the reply was not a JSON object")
        return cast(dict[str, Any], payload)


def classify_error(response: httpx2.Response) -> YouTubeError:
    """Map an unsuccessful reply to a stable code. Uses Google's reason fields, never its text."""
    status = response.status_code
    reasons, detail = _error_reasons(response)
    if reasons & _QUOTA_REASONS:
        return YouTubeError(
            "YOUTUBE_QUOTA_EXHAUSTED",
            "Video suggestions have used up today's allowance. Please try again tomorrow.",
            retryable=False,
            detail=detail,
        )
    if status == 429 or reasons & _BUSY_REASONS:
        return YouTubeError(
            "YOUTUBE_BUSY",
            "YouTube is busy right now.",
            retryable=True,
            detail=detail,
        )
    if status in {401, 403} or reasons & _KEY_REASONS:
        return YouTubeError(
            "YOUTUBE_NOT_AUTHORIZED",
            "Video suggestions aren't set up correctly on this server.",
            retryable=False,
            detail=detail,
        )
    if status == 408 or status >= 500:
        return _unavailable(detail)
    return YouTubeError(
        "YOUTUBE_REJECTED",
        "YouTube couldn't search for this topic.",
        retryable=False,
        detail=detail,
    )


def parse_video(item: dict[str, Any]) -> VideoDetails | None:
    """A ``videos.list`` item as ``VideoDetails``, or None if it lacks an id or a title."""
    video_id = item.get("id")
    snippet = _dict(item.get("snippet"))
    title = _text(snippet.get("title"), _MAX_TITLE_CHARS)
    if not isinstance(video_id, str) or not VIDEO_ID.fullmatch(video_id) or not title:
        return None
    status = _dict(item.get("status"))
    language, source = _language(snippet)
    thumbnail = _thumbnail(_dict(snippet.get("thumbnails")))
    channel_id = snippet.get("channelId")
    category = snippet.get("categoryId")
    return VideoDetails(
        video_id=video_id,
        title=title,
        description=_text(snippet.get("description"), _MAX_DESCRIPTION_CHARS),
        channel_id=channel_id if isinstance(channel_id, str) and len(channel_id) <= 64 else None,
        channel_title=_text(snippet.get("channelTitle"), _MAX_CHANNEL_CHARS),
        published_at=_timestamp(snippet.get("publishedAt")),
        duration_seconds=parse_duration(_dict(item.get("contentDetails")).get("duration")),
        category_id=category if isinstance(category, str) and len(category) <= 8 else None,
        language=language,
        language_source=source,
        thumbnail_url=thumbnail[0] if thumbnail else None,
        thumbnail_width=thumbnail[1] if thumbnail else None,
        thumbnail_height=thumbnail[2] if thumbnail else None,
        view_count=_count(_dict(item.get("statistics")).get("viewCount")),
        watchable=status.get("privacyStatus") == "public"
        and status.get("uploadStatus") == "processed",
        live=snippet.get("liveBroadcastContent", "none") != "none",
    )


def parse_duration(value: object) -> int | None:
    """Seconds in an ISO 8601 duration such as ``PT12M3S``; None if absent, zero or unreadable."""
    if not isinstance(value, str):
        return None
    match = _DURATION.fullmatch(value.strip())
    if match is None:
        return None
    days, hours, minutes, seconds = (int(part) if part else 0 for part in match.groups())
    total = ((days * 24 + hours) * 60 + minutes) * 60 + seconds
    return total or None


def _language(snippet: dict[str, Any]) -> tuple[str | None, LanguageSource]:
    for key, source in (("defaultAudioLanguage", "audio"), ("defaultLanguage", "metadata")):
        value = snippet.get(key)
        if isinstance(value, str) and len(value) <= 16 and _LANGUAGE.fullmatch(value):
            return value, cast(LanguageSource, source)
    return None, "unknown"


def _thumbnail(thumbnails: dict[str, Any]) -> tuple[str, int | None, int | None] | None:
    # "medium" is 320x180, enough for a list; fall back to the others.
    for size in ("medium", "high", "default"):
        entry = _dict(thumbnails.get(size))
        url = entry.get("url")
        if isinstance(url, str) and len(url) <= 500 and _THUMBNAIL.fullmatch(url):
            width, height = _count(entry.get("width")), _count(entry.get("height"))
            return url, width or None, height or None
    return None


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else None


def _count(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _text(value: object, limit: int) -> str:
    """Plain text, whitespace tidied and cut to ``limit`` characters (it is shown, not parsed)."""
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit].strip()


def _error_reasons(response: httpx2.Response) -> tuple[set[str], str]:
    """Google's machine-readable reasons for an error, and a short summary for the logs."""
    summary = f"HTTP {response.status_code}"
    try:
        body: object = response.json()
    except ValueError:
        return set(), summary
    error = _dict(_dict(body).get("error"))
    reasons: set[str] = set()
    for entry in _list(error.get("errors")):
        reason = _dict(entry).get("reason")
        if isinstance(reason, str):
            reasons.add(reason)
    for entry in _list(error.get("details")):
        reason = _dict(entry).get("reason")
        if isinstance(reason, str):
            reasons.add(reason)
    pieces = [summary, ",".join(sorted(reasons)), str(error.get("message") or "").strip()]
    return reasons, ": ".join(piece for piece in pieces if piece)[:_MAX_DETAIL_CHARS]


def _unavailable(detail: str) -> YouTubeError:
    return YouTubeError(
        "YOUTUBE_UNAVAILABLE", "YouTube couldn't be reached.", retryable=True, detail=detail
    )


def _dict(value: object) -> dict[str, Any]:
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _list(value: object) -> list[Any]:
    return cast(list[Any], value) if isinstance(value, list) else []
