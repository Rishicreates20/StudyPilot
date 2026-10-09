"""The signing-key cache: bounded refetching, key rotation, outages, and the HTTP fetcher."""

import asyncio
from collections.abc import Mapping
from typing import Any

import httpx2
import pytest

from app.core.security import AuthUnavailableError, HttpJwksFetcher, JwksCache
from support.keys import SigningKey, jwks_document, make_ec_key

pytestmark = pytest.mark.anyio


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class CountingFetcher:
    def __init__(self, *keys: SigningKey) -> None:
        self.keys = list(keys)
        self.calls = 0
        self.fail = False

    async def __call__(self) -> Mapping[str, Any]:
        self.calls += 1
        if self.fail:
            raise ConnectionError("network down")
        return jwks_document(*self.keys)


def make_cache(fetcher: CountingFetcher, clock: Clock) -> JwksCache:
    return JwksCache(fetcher, ttl=600, refetch_cooldown=30, clock=clock)


async def test_keys_are_fetched_once_and_then_served_from_memory() -> None:
    key = make_ec_key("k1")
    fetcher, clock = CountingFetcher(key), Clock()
    cache = make_cache(fetcher, clock)

    assert await cache.get_key("k1") is not None
    assert await cache.get_key("k1") is not None

    assert fetcher.calls == 1


async def test_keys_are_refreshed_after_the_ttl() -> None:
    fetcher, clock = CountingFetcher(make_ec_key("k1")), Clock()
    cache = make_cache(fetcher, clock)
    await cache.get_key("k1")

    clock.advance(601)
    await cache.get_key("k1")

    assert fetcher.calls == 2


async def test_an_unknown_kid_triggers_a_refetch_that_picks_up_a_rotated_key() -> None:
    old, new = make_ec_key("old"), make_ec_key("new")
    fetcher, clock = CountingFetcher(old), Clock()
    cache = make_cache(fetcher, clock)
    await cache.get_key("old")

    fetcher.keys = [old, new]  # Supabase published a new signing key
    clock.advance(31)

    assert await cache.get_key("new") is not None
    assert fetcher.calls == 2


async def test_a_flood_of_unknown_kids_cannot_hammer_the_key_endpoint() -> None:
    fetcher, clock = CountingFetcher(make_ec_key("k1")), Clock()
    cache = make_cache(fetcher, clock)
    await cache.get_key("k1")

    for index in range(200):
        assert await cache.get_key(f"forged-{index}") is None

    assert fetcher.calls == 1  # all 200 fell inside the 30s cooldown


async def test_unknown_kids_may_refetch_again_once_the_cooldown_passes() -> None:
    fetcher, clock = CountingFetcher(make_ec_key("k1")), Clock()
    cache = make_cache(fetcher, clock)
    await cache.get_key("k1")

    clock.advance(31)
    await cache.get_key("forged")

    assert fetcher.calls == 2


async def test_concurrent_requests_share_a_single_fetch() -> None:
    fetcher, clock = CountingFetcher(make_ec_key("k1")), Clock()
    cache = make_cache(fetcher, clock)

    results = await asyncio.gather(*(cache.get_key("k1") for _ in range(25)))

    assert all(result is not None for result in results)
    assert fetcher.calls == 1


async def test_cached_keys_keep_working_when_a_refresh_fails() -> None:
    fetcher, clock = CountingFetcher(make_ec_key("k1")), Clock()
    cache = make_cache(fetcher, clock)
    await cache.get_key("k1")

    fetcher.fail = True
    clock.advance(601)

    assert await cache.get_key("k1") is not None  # stale-if-error: a brief outage logs nobody out


async def test_with_no_cached_keys_an_outage_is_reported_as_unavailable() -> None:
    fetcher, clock = CountingFetcher(make_ec_key("k1")), Clock()
    fetcher.fail = True
    cache = make_cache(fetcher, clock)

    with pytest.raises(AuthUnavailableError):
        await cache.get_key("k1")


async def test_malformed_key_entries_are_skipped_not_fatal() -> None:
    good = make_ec_key("good")

    async def fetch() -> Mapping[str, Any]:
        return {"keys": ["nonsense", {"kid": "no-material"}, {"no": "kid"}, good.public_jwk]}

    cache = JwksCache(fetch)

    assert await cache.get_key("good") is not None
    assert await cache.get_key("no-material") is None


# --- The HTTP fetcher ------------------------------------------------------------------------


def http_fetcher(handler: Any) -> HttpJwksFetcher:
    client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    return HttpJwksFetcher(client, "https://project.supabase.co/auth/v1/.well-known/jwks.json")


async def test_the_http_fetcher_returns_the_published_keys() -> None:
    key = make_ec_key("k1")
    seen: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(str(request.url))
        return httpx2.Response(200, json=jwks_document(key))

    document = await http_fetcher(handler)()

    assert seen == ["https://project.supabase.co/auth/v1/.well-known/jwks.json"]
    assert document["keys"][0]["kid"] == "k1"


@pytest.mark.parametrize(
    "response",
    [
        httpx2.Response(500),
        httpx2.Response(404),
        httpx2.Response(200, text="<html>not json</html>"),
        httpx2.Response(200, json={"unexpected": True}),
        httpx2.Response(200, json=["keys"]),
    ],
)
async def test_the_http_fetcher_raises_on_bad_responses(response: httpx2.Response) -> None:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        return response

    fetcher = http_fetcher(handler)

    with pytest.raises(Exception):  # noqa: B017 - any failure must reach the cache's handler
        await fetcher()
