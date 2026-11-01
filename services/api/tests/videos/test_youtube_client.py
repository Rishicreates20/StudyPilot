"""The YouTube Data API client, against a mock HTTP transport (no network, no real key)."""

import httpx2
import pytest

from app.videos.youtube import YouTubeError
from support.youtube import KEY, FakeYouTube, google_error, video_item

pytestmark = pytest.mark.anyio


async def test_search_sends_the_query_and_language_and_returns_ids_in_order() -> None:
    youtube = FakeYouTube()
    youtube.add("hi", video_item("bbbbbbbbbbb", "B"), video_item("aaaaaaaaaaa", "A"))

    ids = await youtube.client().search("gati ke niyam", language="hi", max_results=10)

    assert ids == ["bbbbbbbbbbb", "aaaaaaaaaaa"]
    (request,) = youtube.requests
    params = request.url.params
    assert request.url.path == "/youtube/v3/search"
    assert params["q"] == "gati ke niyam"
    assert params["relevanceLanguage"] == "hi"
    assert params["type"] == "video"
    assert params["safeSearch"] == "strict"
    assert params["maxResults"] == "10"


async def test_the_key_travels_in_a_header_never_in_the_url() -> None:
    youtube = FakeYouTube()
    await youtube.client().search("anything", language="en", max_results=5)

    (request,) = youtube.requests
    assert request.headers["x-goog-api-key"] == KEY
    assert KEY not in str(request.url)
    assert "key" not in request.url.params


async def test_search_ignores_anything_that_is_not_a_video_id() -> None:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        items = [
            {"id": {"videoId": "goodvideo01"}},
            {"id": {"videoId": "bad"}},
            {"id": {"channelId": "UC-x"}},
            {"id": {"videoId": "javascript:x"}},
            {"id": {"videoId": "goodvideo01"}},
            "nonsense",
        ]
        return httpx2.Response(200, json={"items": items})

    youtube = FakeYouTube()
    youtube.handler = handler  # type: ignore[method-assign]
    assert await youtube.client().search("q", language="en", max_results=5) == ["goodvideo01"]


async def test_details_are_read_from_videos_list() -> None:
    youtube = FakeYouTube()
    youtube.add(
        "en",
        video_item(
            "aaaaaaaaaaa",
            "  Ownership   explained ",
            description="Line one\nLine two",
            duration="PT1H2M3S",
            views="98765",
            audio_language=None,
        ),
    )
    youtube.items["aaaaaaaaaaa"]["snippet"]["defaultLanguage"] = "en-GB"

    (details,) = await youtube.client().videos(["aaaaaaaaaaa", "missingvid1"])

    assert details.title == "Ownership explained"
    assert details.description == "Line one Line two"
    assert details.duration_seconds == 3723
    assert details.view_count == 98765
    assert (details.language, details.language_source) == ("en-GB", "metadata")
    assert details.thumbnail_url == "https://i.ytimg.com/vi/aaaaaaaaaaa/mqdefault.jpg"
    assert (details.thumbnail_width, details.thumbnail_height) == (320, 180)
    assert details.published_at is not None and details.published_at.year == 2025
    assert details.watchable is True and details.live is False
    (request,) = youtube.calls("videos")
    assert request.url.params["id"] == "aaaaaaaaaaa,missingvid1"


async def test_private_unprocessed_and_live_videos_are_flagged() -> None:
    youtube = FakeYouTube()
    youtube.add(
        "en",
        video_item("privatevid1", "P", privacy="private"),
        video_item("uploadingv1", "U", upload="uploaded"),
        video_item("livestream1", "L", live="live", duration="PT0S"),
    )

    found = {v.video_id: v for v in await youtube.client().videos(list(youtube.items))}

    assert found["privatevid1"].watchable is False
    assert found["uploadingv1"].watchable is False
    assert found["livestream1"].live is True and found["livestream1"].duration_seconds is None


async def test_a_thumbnail_that_is_not_https_is_dropped() -> None:
    youtube = FakeYouTube()
    youtube.add("en", video_item("aaaaaaaaaaa", "A"))
    youtube.items["aaaaaaaaaaa"]["snippet"]["thumbnails"] = {
        "medium": {"url": "http://i.ytimg.com/x.jpg"},
        "high": {"url": "javascript:alert(1)"},
    }

    (details,) = await youtube.client().videos(["aaaaaaaaaaa"])

    assert details.thumbnail_url is None


async def test_no_ids_means_no_call() -> None:
    youtube = FakeYouTube()
    assert await youtube.client().videos(["not-an-id"]) == []
    assert youtube.requests == []


@pytest.mark.parametrize(
    ("status", "body", "code", "retryable"),
    [
        (403, google_error(403, "quotaExceeded"), "YOUTUBE_QUOTA_EXHAUSTED", False),
        (403, google_error(403, "dailyLimitExceeded"), "YOUTUBE_QUOTA_EXHAUSTED", False),
        (403, google_error(403, "rateLimitExceeded"), "YOUTUBE_BUSY", True),
        (429, {"error": {"code": 429}}, "YOUTUBE_BUSY", True),
        (400, google_error(400, "keyInvalid"), "YOUTUBE_NOT_AUTHORIZED", False),
        (403, google_error(403, "accessNotConfigured"), "YOUTUBE_NOT_AUTHORIZED", False),
        (403, google_error(403, "forbidden"), "YOUTUBE_NOT_AUTHORIZED", False),
        (503, google_error(503, "backendError"), "YOUTUBE_UNAVAILABLE", True),
        (500, "not json", "YOUTUBE_UNAVAILABLE", True),
        (400, google_error(400, "invalidSearchFilter"), "YOUTUBE_REJECTED", False),
    ],
)
async def test_errors_map_to_stable_codes(
    status: int, body: object, code: str, retryable: bool
) -> None:
    youtube = FakeYouTube(failures={"search": (status, body)})

    with pytest.raises(YouTubeError) as caught:
        await youtube.client().search("q", language="en", max_results=5)

    assert (caught.value.code, caught.value.retryable) == (code, retryable)
    assert caught.value.message  # something a learner can read
    assert "Something went wrong" not in caught.value.message  # Google's text stays in the logs


async def test_a_timeout_is_retryable_and_says_nothing_about_the_host() -> None:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectTimeout("timed out connecting to youtube.test")

    youtube = FakeYouTube()
    youtube.handler = handler  # type: ignore[method-assign]
    with pytest.raises(YouTubeError) as caught:
        await youtube.client().search("q", language="en", max_results=5)

    assert caught.value.code == "YOUTUBE_UNAVAILABLE" and caught.value.retryable
    assert "youtube.test" not in caught.value.detail


async def test_a_reply_that_is_not_an_object_is_unavailable() -> None:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=["not", "an", "object"])

    youtube = FakeYouTube()
    youtube.handler = handler  # type: ignore[method-assign]
    with pytest.raises(YouTubeError) as caught:
        await youtube.client().search("q", language="en", max_results=5)

    assert caught.value.code == "YOUTUBE_UNAVAILABLE"
