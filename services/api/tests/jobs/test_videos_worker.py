"""The worker finding study videos for real: queue -> YouTube (mocked) -> ranking -> PostgreSQL."""

import uuid
from typing import Any

import pytest
from psycopg.types.json import Jsonb

from app.core.db import Database
from app.jobs.worker import Worker
from app.videos.quota import quota_day
from support.database import admin
from support.lessons import Seeded, seed_learning_state
from support.rows import add_job
from support.worker import job_state, make_env, worker_settings
from support.youtube import FakeYouTube, google_error, video_item

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _empty_quota_ledger(database_dsn: str) -> None:
    """The ledger is shared by the whole server (and this test session): start each test at 0."""
    admin(database_dsn).execute("delete from public.youtube_quota_usage")


def worker_for(
    database: Database, dsn: str, youtube: FakeYouTube | None, **settings: Any
) -> Worker:
    config = worker_settings(dsn, **settings)
    return Worker(make_env(database, config, None, videos=youtube.client() if youtube else None))


def seed_search_job(
    dsn: str, *, topic: int = 0, request: dict[str, Any] | None = None, **fields: Any
) -> tuple[Seeded, uuid.UUID, uuid.UUID]:
    """A learner with a roadmap and a queued video search for one topic: (seeded, item, job)."""
    seeded = seed_learning_state(dsn)
    item = seeded.topics[topic]
    admin(dsn).execute(
        "update public.roadmap_items set title = 'Ownership and borrowing' where id = %s", (item,)
    )
    job = add_job(
        dsn,
        seeded.user,
        seeded.goal,
        job_type="resources",
        item_id=item,
        request=Jsonb(request or {}),
        **fields,
    )
    return seeded, item, job


def good_videos(prefix: str = "good", count: int = 3) -> list[dict[str, Any]]:
    return [
        video_item(
            f"{prefix}{n:0{11 - len(prefix)}d}",
            f"Rust ownership and borrowing, part {n}",
            channel_id=f"UC-{prefix}-{n}",
            channel_title=f"Channel {n}",
        )
        for n in range(1, count + 1)
    ]


def searches_of(dsn: str, item: uuid.UUID) -> list[dict[str, Any]]:
    rows = admin(dsn).fetchall("select * from public.resource_searches where item_id = %s", (item,))
    return [dict(row) for row in rows]


def videos_of(dsn: str, item: uuid.UUID) -> list[dict[str, Any]]:
    rows = admin(dsn).fetchall(
        "select * from public.topic_resources where item_id = %s order by position", (item,)
    )
    return [dict(row) for row in rows]


def ledger(dsn: str) -> list[tuple[str, int]]:
    rows = admin(dsn).fetchall(
        "select endpoint, units from public.youtube_quota_usage where day = %s order by id",
        (quota_day(),),
    )
    return [(row["endpoint"], row["units"]) for row in rows]


# --- The happy path --------------------------------------------------------------------------


async def test_a_queued_search_becomes_stored_ranked_videos(
    database: Database, database_dsn: str
) -> None:
    seeded, item, job = seed_search_job(database_dsn)
    youtube = FakeYouTube()
    youtube.add("en", *good_videos())

    assert await worker_for(database, database_dsn, youtube).run_once() is True

    state = job_state(database_dsn, job)
    assert (state["status"], state["stage"], state["progress"]) == ("completed", "done", 100)
    (search,) = searches_of(database_dsn, item)
    assert search["user_id"] == seeded.user and search["job_id"] == job
    assert search["roadmap_id"] == seeded.roadmap and search["provider"] == "youtube"
    assert search["languages"] == ["en"]
    assert search["queries"] == ["Ownership and borrowing kubernetes"]
    assert (search["candidates_seen"], search["result_count"]) == (3, 3)
    assert search["units_spent"] == 101
    videos = videos_of(database_dsn, item)
    assert [v["position"] for v in videos] == [1, 2, 3]
    for row in videos:
        assert row["user_id"] == seeded.user and row["search_id"] == search["id"]
        assert row["url"] == f"https://www.youtube.com/watch?v={row['external_id']}"
        assert row["language"] == "en" and row["language_source"] == "audio"
        assert row["searched_language"] == "en" and row["status"] == "available"
        assert row["duration_seconds"] == 750 and row["category_id"] == "27"
        assert 0 <= row["relevance_score"] <= 100
        assert sum(row["score_basis"].values()) == row["relevance_score"]
    assert ledger(database_dsn) == [("search.list", 100), ("videos.list", 1)]


async def test_unsuitable_videos_are_not_stored(database: Database, database_dsn: str) -> None:
    _, item, _ = seed_search_job(database_dsn)
    youtube = FakeYouTube()
    youtube.add(
        "en",
        *good_videos(count=1),
        video_item("shortvideo1", "Ownership in 30 seconds", duration="PT30S"),
        video_item("privatevid1", "Ownership private", privacy="private"),
        video_item("offtopic001", "Cooking pasta", description="Dinner"),
    )

    await worker_for(database, database_dsn, youtube).run_once()

    (search,) = searches_of(database_dsn, item)
    assert (search["candidates_seen"], search["result_count"]) == (4, 1)
    assert [v["external_id"] for v in videos_of(database_dsn, item)] == ["good0000001"]


async def test_finding_nothing_suitable_is_a_finished_search(
    database: Database, database_dsn: str
) -> None:
    _, item, job = seed_search_job(database_dsn)

    await worker_for(database, database_dsn, FakeYouTube()).run_once()

    assert job_state(database_dsn, job)["status"] == "completed"
    (search,) = searches_of(database_dsn, item)
    assert search["result_count"] == 0 and videos_of(database_dsn, item) == []


async def test_a_new_search_replaces_the_topics_old_one(
    database: Database, database_dsn: str
) -> None:
    seeded, item, _ = seed_search_job(database_dsn)
    first = FakeYouTube()
    first.add("en", *good_videos("old"))
    await worker_for(database, database_dsn, first).run_once()

    add_job(
        database_dsn,
        seeded.user,
        seeded.goal,
        job_type="resources",
        item_id=item,
        request=Jsonb({"refresh": True}),
    )
    second = FakeYouTube()
    second.add("en", *good_videos("new", count=2))
    await worker_for(database, database_dsn, second).run_once()

    assert len(searches_of(database_dsn, item)) == 1
    assert [v["external_id"][:3] for v in videos_of(database_dsn, item)] == ["new", "new"]


# --- Languages -------------------------------------------------------------------------------


async def test_another_language_is_searched_first_then_english_when_it_found_too_few(
    database: Database, database_dsn: str
) -> None:
    seeded, item, _ = seed_search_job(database_dsn)
    admin(database_dsn).execute(
        "update public.roadmaps set language = 'hi' where id = %s", (seeded.roadmap,)
    )
    youtube = FakeYouTube()
    youtube.add("hi", *good_videos("hin", count=1))
    for video in youtube.items.values():
        video["snippet"]["defaultAudioLanguage"] = "hi"
    youtube.add("en", *good_videos("eng", count=2))

    await worker_for(database, database_dsn, youtube).run_once()

    assert [r.url.params["relevanceLanguage"] for r in youtube.calls("search")] == ["hi", "en"]
    (search,) = searches_of(database_dsn, item)
    assert search["languages"] == ["hi", "en"] and search["units_spent"] == 202
    by_id = {v["external_id"]: v for v in videos_of(database_dsn, item)}
    assert by_id["hin00000001"]["searched_language"] == "hi"
    assert by_id["hin00000001"]["language"] == "hi"
    assert by_id["eng00000001"]["searched_language"] == "en"


async def test_english_is_not_searched_when_the_first_language_found_enough(
    database: Database, database_dsn: str
) -> None:
    seeded, _, _ = seed_search_job(database_dsn)
    admin(database_dsn).execute(
        "update public.roadmaps set language = 'hi' where id = %s", (seeded.roadmap,)
    )
    youtube = FakeYouTube()
    youtube.add("hi", *good_videos("hin", count=3))

    await worker_for(database, database_dsn, youtube, youtube_videos_per_topic=3).run_once()

    assert [r.url.params["relevanceLanguage"] for r in youtube.calls("search")] == ["hi"]


# --- Quota, failures and retries --------------------------------------------------------------


async def test_the_servers_daily_allowance_stops_a_search_before_it_calls_youtube(
    database: Database, database_dsn: str
) -> None:
    _, item, job = seed_search_job(database_dsn)
    admin(database_dsn).execute(
        "insert into public.youtube_quota_usage (day, endpoint, units) values (%s, 'search.list',"
        " 950)",
        (quota_day(),),
    )
    youtube = FakeYouTube()
    youtube.add("en", *good_videos())

    await worker_for(database, database_dsn, youtube, youtube_daily_units=1000).run_once()

    state = job_state(database_dsn, job)
    assert (state["status"], state["error_code"]) == ("failed", "YOUTUBE_DAILY_LIMIT")
    assert "tomorrow" in state["error_message"]
    assert youtube.requests == [] and searches_of(database_dsn, item) == []


async def test_youtubes_own_quota_error_fails_the_search_without_retrying(
    database: Database, database_dsn: str
) -> None:
    _, item, job = seed_search_job(database_dsn)
    youtube = FakeYouTube(failures={"search": (403, google_error(403, "quotaExceeded"))})

    await worker_for(database, database_dsn, youtube).run_once()

    state = job_state(database_dsn, job)
    assert (state["status"], state["error_code"], state["attempts"]) == (
        "failed",
        "YOUTUBE_QUOTA_EXHAUSTED",
        1,
    )
    assert searches_of(database_dsn, item) == []
    # The call was made, so its units count.
    assert ledger(database_dsn) == [("search.list", 100)]


async def test_youtube_being_unreachable_is_retried_later(
    database: Database, database_dsn: str
) -> None:
    _, _, job = seed_search_job(database_dsn)
    youtube = FakeYouTube(failures={"search": (503, google_error(503, "backendError"))})

    await worker_for(database, database_dsn, youtube).run_once()

    state = job_state(database_dsn, job)
    assert (state["status"], state["stage"], state["error_code"]) == (
        "queued",
        "waiting_retry",
        "YOUTUBE_UNAVAILABLE",
    )


async def test_without_a_key_the_search_fails_with_a_clear_reason(
    database: Database, database_dsn: str
) -> None:
    _, _, job = seed_search_job(database_dsn)

    await worker_for(database, database_dsn, None).run_once()

    state = job_state(database_dsn, job)
    assert (state["status"], state["error_code"]) == ("failed", "VIDEOS_NOT_CONFIGURED")


async def test_an_archived_goal_is_not_searched_for(database: Database, database_dsn: str) -> None:
    seeded, _, job = seed_search_job(database_dsn)
    admin(database_dsn).execute(
        "update public.learning_goals set status = 'archived' where id = %s", (seeded.goal,)
    )
    youtube = FakeYouTube()

    await worker_for(database, database_dsn, youtube).run_once()

    assert job_state(database_dsn, job)["error_code"] == "GOAL_UNAVAILABLE"
    assert youtube.requests == []


async def test_a_checkpointed_search_is_saved_without_searching_again(
    database: Database, database_dsn: str
) -> None:
    seeded, item, first_job = seed_search_job(database_dsn)
    first = FakeYouTube()
    first.add("en", *good_videos())
    await worker_for(database, database_dsn, first).run_once()
    stored = videos_of(database_dsn, item)
    # The ranked result was checkpointed before it was saved. Pretend the save was lost and the
    # job came back with that checkpoint: it must be stored again without asking YouTube.
    checkpoint = job_state(database_dsn, first_job)["checkpoint"]
    assert checkpoint is not None
    admin(database_dsn).execute("delete from public.resource_searches where item_id = %s", (item,))
    job = add_job(
        database_dsn,
        seeded.user,
        seeded.goal,
        job_type="resources",
        item_id=item,
        checkpoint=Jsonb(checkpoint),
    )
    second = FakeYouTube()

    await worker_for(database, database_dsn, second).run_once()

    assert job_state(database_dsn, job)["status"] == "completed"
    assert second.requests == []
    again = videos_of(database_dsn, item)
    assert [(v["external_id"], v["relevance_score"], v["score_basis"]) for v in again] == [
        (v["external_id"], v["relevance_score"], v["score_basis"]) for v in stored
    ]
    assert [v["published_at"] for v in again] == [v["published_at"] for v in stored]


async def test_a_cancel_that_lands_during_the_search_wins(
    database: Database, database_dsn: str
) -> None:
    _, item, job = seed_search_job(database_dsn)
    youtube = FakeYouTube()
    youtube.add("en", *good_videos())
    answer = youtube.handler

    def cancel_then_answer(request: Any) -> Any:
        admin(database_dsn).execute(
            "update public.generation_jobs set cancel_requested = true where id = %s", (job,)
        )
        return answer(request)

    youtube.handler = cancel_then_answer  # type: ignore[method-assign]

    await worker_for(database, database_dsn, youtube).run_once()

    assert job_state(database_dsn, job)["status"] == "cancelled"
    assert searches_of(database_dsn, item) == []


# --- Retention --------------------------------------------------------------------------------


async def test_searches_not_confirmed_for_30_days_are_deleted(
    database: Database, database_dsn: str
) -> None:
    _, item, _ = seed_search_job(database_dsn)
    youtube = FakeYouTube()
    youtube.add("en", *good_videos())
    worker = worker_for(database, database_dsn, youtube)
    await worker.run_once()

    await worker.reap_once()
    assert len(videos_of(database_dsn, item)) == 3  # fresh: kept

    admin(database_dsn).execute(
        "update public.resource_searches set last_verified_at = now() - interval '31 days'"
        " where item_id = %s",
        (item,),
    )
    await worker.reap_once()

    assert searches_of(database_dsn, item) == [] and videos_of(database_dsn, item) == []
