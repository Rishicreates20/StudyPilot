"""The worker's reads and writes for video searches (privileged connection; filters on user_id).

``save_search`` is the only place suggestions are stored. It runs in the transaction that
completes the job: the topic's previous search (and its videos) is replaced by the new one, so a
topic has at most one search and a learner never sees half of one.

The quota ledger (``youtube_quota_usage``) belongs to the server, not to a learner: units are
reserved under a transaction-scoped advisory lock *before* each call, so two workers cannot both
spend the last of the day's allowance, and a call that is cut off still counts.
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from app.core.db import SystemConnection
from app.jobs.errors import JobCancelled, LeaseLost
from app.jobs.queue import Job
from app.videos.model import LanguageSource, RankedVideo, SearchOutcome, VideoDetails, watch_url

# Searches nobody has confirmed with YouTube for this long are deleted (YouTube's developer
# policies allow keeping API data for 30 days without refreshing it).
RETENTION_DAYS = 30
# Any fixed number: names the advisory lock that serialises reservations of quota units.
_QUOTA_LOCK = 51_000_051


@dataclass(frozen=True)
class VideoTopic:
    item_id: UUID
    kind: str
    title: str
    roadmap_status: str
    language: str
    goal_title: str
    goal_status: str


async def load_topic(
    connection: SystemConnection, user_id: UUID, item_id: UUID
) -> VideoTopic | None:
    cursor = await connection.execute(
        "select i.id as item_id, i.kind, i.title, r.status as roadmap_status, r.language,"
        " g.title as goal_title, g.status as goal_status"
        " from public.roadmap_items i"
        " join public.roadmaps r on r.id = i.roadmap_id and r.user_id = i.user_id"
        " join public.learning_goals g on g.id = r.goal_id and g.user_id = r.user_id"
        " where i.id = %s and i.user_id = %s",
        (item_id, user_id),
    )
    row = await cursor.fetchone()
    return VideoTopic(**row) if row else None


async def reserve_units(
    connection: SystemConnection, *, day: date, endpoint: str, units: int, daily_limit: int
) -> bool:
    """Record ``units`` against ``day`` if the server's allowance has room; False if it has not."""
    await connection.execute("select pg_advisory_xact_lock(%s)", (_QUOTA_LOCK,))
    cursor = await connection.execute(
        "select coalesce(sum(units), 0) as spent from public.youtube_quota_usage where day = %s",
        (day,),
    )
    row = await cursor.fetchone()
    spent = int(row["spent"]) if row else 0
    if spent + units > daily_limit:
        return False
    await connection.execute(
        "insert into public.youtube_quota_usage (day, endpoint, units) values (%s, %s, %s)",
        (day, endpoint, units),
    )
    return True


async def hold_job(connection: SystemConnection, job: Job, worker_id: str) -> None:
    """Lock the job row and confirm this worker still owns it and nobody cancelled it."""
    cursor = await connection.execute(
        "select cancel_requested from public.generation_jobs"
        " where id = %s and locked_by = %s and status = 'running' for update",
        (job.id, worker_id),
    )
    owned = await cursor.fetchone()
    if owned is None:
        raise LeaseLost
    if owned["cancel_requested"]:
        raise JobCancelled


async def save_search(
    connection: SystemConnection, job: Job, item_id: UUID, outcome: SearchOutcome
) -> UUID:
    """Replace the topic's suggestions with ``outcome``. Returns the new search's id."""
    await connection.execute(
        "delete from public.resource_searches where item_id = %s and user_id = %s",
        (item_id, job.user_id),
    )
    cursor = await connection.execute(
        "insert into public.resource_searches (user_id, roadmap_id, item_id, job_id, provider,"
        " languages, queries, candidates_seen, result_count, units_spent)"
        " select i.user_id, i.roadmap_id, i.id, %s, 'youtube', %s, %s, %s, %s, %s"
        " from public.roadmap_items i where i.id = %s and i.user_id = %s"
        " returning id",
        (
            job.id,
            list(outcome.languages),
            list(outcome.queries),
            outcome.candidates_seen,
            len(outcome.videos),
            outcome.units_spent,
            item_id,
            job.user_id,
        ),
    )
    row = await cursor.fetchone()
    if row is None:
        raise LookupError("the topic no longer exists")
    search_id: UUID = row["id"]
    for video in outcome.videos:
        details = video.details
        await connection.execute(
            "insert into public.topic_resources (user_id, search_id, item_id, provider,"
            " external_id, title, description, channel_id, channel_title, url, language,"
            " language_source, searched_language, published_at, duration_seconds, thumbnail_url,"
            " thumbnail_width, thumbnail_height, category_id, view_count, relevance_score,"
            " score_basis, position, last_verified_at)"
            " values (%s, %s, %s, 'youtube', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,"
            " %s, %s, %s, %s, %s, %s, %s, now())",
            (
                job.user_id,
                search_id,
                item_id,
                details.video_id,
                details.title,
                details.description,
                details.channel_id,
                details.channel_title,
                watch_url(details.video_id),
                details.language,
                details.language_source,
                video.searched_language,
                details.published_at,
                details.duration_seconds,
                details.thumbnail_url,
                details.thumbnail_width,
                details.thumbnail_height,
                details.category_id,
                details.view_count,
                video.relevance_score,
                Jsonb(video.score_basis),
                video.position,
            ),
        )
    return search_id


async def purge_unverified(connection: SystemConnection) -> int:
    """Delete searches (and their videos) not confirmed with YouTube in ``RETENTION_DAYS``."""
    cursor = await connection.execute(
        "delete from public.resource_searches"
        " where last_verified_at < now() - %s * interval '1 day'",
        (RETENTION_DAYS,),
    )
    return cursor.rowcount


# --- Checkpoints: a finished search survives a failed save without being paid for twice --------


def checkpoint_of(outcome: SearchOutcome) -> dict[str, Any]:
    return {
        "languages": list(outcome.languages),
        "queries": list(outcome.queries),
        "candidates_seen": outcome.candidates_seen,
        "units_spent": outcome.units_spent,
        "videos": [
            {
                "details": {
                    **{k: v for k, v in vars(video.details).items() if k != "published_at"},
                    "published_at": video.details.published_at.isoformat()
                    if video.details.published_at
                    else None,
                },
                "searched_language": video.searched_language,
                "relevance_score": video.relevance_score,
                "score_basis": video.score_basis,
                "position": video.position,
            }
            for video in outcome.videos
        ],
    }


def restore_checkpoint(data: dict[str, Any]) -> SearchOutcome:
    videos: list[RankedVideo] = []
    for entry in data["videos"]:
        raw = dict(entry["details"])
        published = raw.pop("published_at")
        source: LanguageSource = raw.pop("language_source")
        videos.append(
            RankedVideo(
                details=VideoDetails(
                    **raw,
                    language_source=source,
                    published_at=datetime.fromisoformat(published) if published else None,
                ),
                searched_language=entry["searched_language"],
                relevance_score=int(entry["relevance_score"]),
                score_basis={str(k): int(v) for k, v in entry["score_basis"].items()},
                position=int(entry["position"]),
            )
        )
    return SearchOutcome(
        languages=tuple(data["languages"]),
        queries=tuple(data["queries"]),
        candidates_seen=int(data["candidates_seen"]),
        units_spent=int(data["units_spent"]),
        videos=tuple(videos),
    )
