"""A stand-in for the YouTube Data API, on a mock HTTP transport (no network, no real key)."""

from dataclasses import dataclass, field
from typing import Any

import httpx2
from pydantic import SecretStr

from app.videos.youtube import YouTubeClient

KEY = "test-youtube-key-not-a-real-secret"
BASE_URL = "https://youtube.test/youtube/v3"


def video_item(
    video_id: str,
    title: str,
    *,
    description: str = "",
    channel_id: str = "UC-channel-a",
    channel_title: str = "A channel",
    duration: str = "PT12M30S",
    category: str = "27",
    audio_language: str | None = "en",
    views: str | None = "120000",
    privacy: str = "public",
    upload: str = "processed",
    live: str = "none",
) -> dict[str, Any]:
    """One ``videos.list`` item, shaped like YouTube's (only the fields this app reads)."""
    snippet: dict[str, Any] = {
        "title": title,
        "description": description,
        "channelId": channel_id,
        "channelTitle": channel_title,
        "publishedAt": "2025-03-04T05:06:07Z",
        "categoryId": category,
        "liveBroadcastContent": live,
        "thumbnails": {
            "medium": {
                "url": f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg",
                "width": 320,
                "height": 180,
            }
        },
    }
    if audio_language:
        snippet["defaultAudioLanguage"] = audio_language
    item: dict[str, Any] = {
        "id": video_id,
        "snippet": snippet,
        "contentDetails": {"duration": duration},
        "status": {"privacyStatus": privacy, "uploadStatus": upload},
        "statistics": {"viewCount": views} if views is not None else {},
    }
    return item


@dataclass
class FakeYouTube:
    """Answers ``search`` from ``results`` (by language) and ``videos`` from ``items``.

    ``failures`` maps an endpoint (``search`` or ``videos``) to a (status, body) reply given
    instead of the real answer. Every request is kept in ``requests``.
    """

    results: dict[str, list[str]] = field(default_factory=dict[str, list[str]])
    items: dict[str, dict[str, Any]] = field(default_factory=dict[str, dict[str, Any]])
    failures: dict[str, tuple[int, Any]] = field(default_factory=dict[str, tuple[int, Any]])
    requests: list[httpx2.Request] = field(default_factory=list[httpx2.Request])

    def add(self, language: str, *items: dict[str, Any]) -> None:
        """Make ``items`` the search results for ``language`` (and known to ``videos``)."""
        self.results[language] = [item["id"] for item in items]
        for item in items:
            self.items[item["id"]] = item

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        endpoint = request.url.path.rsplit("/", 1)[-1]
        if endpoint in self.failures:
            status, body = self.failures[endpoint]
            return httpx2.Response(status, json=body)
        if endpoint == "search":
            language = request.url.params.get("relevanceLanguage", "")
            ids = self.results.get(language, [])
            return httpx2.Response(200, json={"items": [{"id": {"videoId": i}} for i in ids]})
        if endpoint == "videos":
            wanted = request.url.params.get("id", "").split(",")
            return httpx2.Response(
                200, json={"items": [self.items[i] for i in wanted if i in self.items]}
            )
        return httpx2.Response(404, json={"error": {"code": 404}})

    def client(self) -> YouTubeClient:
        return YouTubeClient(
            httpx2.AsyncClient(transport=httpx2.MockTransport(self.handler)),
            api_key=SecretStr(KEY),
            base_url=BASE_URL,
            timeout_seconds=5,
        )

    def calls(self, endpoint: str) -> list[httpx2.Request]:
        return [r for r in self.requests if r.url.path.endswith(f"/{endpoint}")]


def google_error(status: int, reason: str, message: str = "Something went wrong") -> dict[str, Any]:
    """An error body in the shape Google APIs use."""
    return {
        "error": {
            "code": status,
            "message": message,
            "errors": [{"message": message, "domain": "youtube", "reason": reason}],
        }
    }
