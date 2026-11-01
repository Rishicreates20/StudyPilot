"""Running one video search (a ``resources`` job): find, check, rank and store study videos.

Stages (``generation_jobs.stage`` / ``progress``): loading 10 -> searching 30 -> checking 60 ->
saving 90 -> done 100. No model is involved: the videos and every fact shown about them come from
the YouTube Data API, ranked by the rules in ``app/videos/ranking.py``. The topic's roadmap
language is searched first; English is searched as well when that is another language and the
first search did not find enough. Quota units are reserved before each call, and the ranked result
is checkpointed before it is saved, so a retry after a failed save does not search (or pay) again.

How a job *ends* (retries, failures, cancellation) is decided in ``runner.py``.
"""

from collections.abc import Awaitable

import structlog

from app.jobs import queue, videos_store
from app.jobs.errors import JobFailure, LeaseLost
from app.jobs.queue import Job
from app.jobs.runtime import Lease, WorkerEnv, set_stage
from app.videos.model import RankedVideo, SearchOutcome, VideoDetails
from app.videos.quota import quota_day
from app.videos.ranking import rank_videos, search_languages, search_query
from app.videos.youtube import DETAILS_BATCH, DETAILS_UNITS, SEARCH_UNITS, YouTubeError

log = structlog.get_logger("app.jobs")


async def run_videos(env: WorkerEnv, job: Job, lease: Lease) -> None:
    await set_stage(env, job, "loading", 10)
    lease.check()
    if job.item_id is None:  # the database forbids this; stay safe if it ever happens
        raise JobFailure("TOPIC_UNAVAILABLE", "This video search has no topic.")
    async with env.database.system_session() as connection:
        topic = await videos_store.load_topic(connection, job.user_id, job.item_id)
    if topic is None:
        raise JobFailure("TOPIC_UNAVAILABLE", "This topic no longer exists.")
    if topic.goal_status == "archived":
        raise JobFailure("GOAL_UNAVAILABLE", "This goal is archived. Restore it to find videos.")
    if topic.kind == "revision":
        raise JobFailure("TOPIC_UNAVAILABLE", "Revision sessions don't have video suggestions.")

    if job.checkpoint:
        outcome = videos_store.restore_checkpoint(job.checkpoint)
    else:
        outcome = await _search(env, job, lease, topic)
        async with env.database.system_session() as connection:
            if not await queue.save_checkpoint(
                connection, job.id, env.worker_id, videos_store.checkpoint_of(outcome)
            ):
                raise LeaseLost

    await set_stage(env, job, "saving", 90)
    lease.check()
    async with env.database.system_session() as connection:
        # A cancel that landed while searching wins: nothing is stored.
        await videos_store.hold_job(connection, job, env.worker_id)
        try:
            search_id = await videos_store.save_search(connection, job, topic.item_id, outcome)
        except LookupError:
            raise JobFailure("TOPIC_UNAVAILABLE", "This topic no longer exists.") from None
        if not await queue.complete(connection, job.id, env.worker_id):
            raise LeaseLost  # rolls the whole transaction back
    log.info(
        "videos.saved",
        job_id=str(job.id),
        search_id=str(search_id),
        languages=list(outcome.languages),
        candidates=outcome.candidates_seen,
        kept=len(outcome.videos),
        units=outcome.units_spent,
    )


async def _search(
    env: WorkerEnv, job: Job, lease: Lease, topic: videos_store.VideoTopic
) -> SearchOutcome:
    client = env.videos
    if client is None:
        raise JobFailure("VIDEOS_NOT_CONFIGURED", "Video suggestions aren't set up on this server.")
    settings = env.settings
    query = search_query(topic.title, topic.goal_title)
    if not query:
        raise JobFailure("TOPIC_UNAVAILABLE", "This topic has no title to search for.")

    languages: list[str] = []
    found: dict[str, tuple[str, int, int]] = {}  # video id -> (language, rank, result count)
    details: dict[str, VideoDetails] = {}
    units = 0
    kept: list[RankedVideo] = []
    for language in search_languages(topic.language):
        await set_stage(env, job, "searching", 30)
        lease.check()
        await _reserve(env, "search.list", SEARCH_UNITS)
        units += SEARCH_UNITS
        ids = await _call(
            client.search(
                query, language=language, max_results=settings.youtube_candidates_per_search
            )
        )
        languages.append(language)
        for rank, video_id in enumerate(ids, start=1):
            found.setdefault(video_id, (language, rank, len(ids)))

        await set_stage(env, job, "checking", 60)
        lease.check()
        missing = [video_id for video_id in found if video_id not in details]
        for start in range(0, len(missing), DETAILS_BATCH):
            await _reserve(env, "videos.list", DETAILS_UNITS)
            units += DETAILS_UNITS
            for video in await _call(client.videos(missing[start : start + DETAILS_BATCH])):
                details[video.video_id] = video

        kept = rank_videos(
            ((details[video_id], *found[video_id]) for video_id in found if video_id in details),
            topic_title=topic.title,
            limit=settings.youtube_videos_per_topic,
        )
        if len(kept) >= settings.youtube_videos_per_topic:
            break

    return SearchOutcome(
        languages=tuple(languages),
        # The same words are sent for every language; recorded once per search made.
        queries=tuple(query for _ in languages),
        candidates_seen=len(found),
        units_spent=units,
        videos=tuple(kept),
    )


async def _reserve(env: WorkerEnv, endpoint: str, units: int) -> None:
    async with env.database.system_session() as connection:
        reserved = await videos_store.reserve_units(
            connection,
            day=quota_day(),
            endpoint=endpoint,
            units=units,
            daily_limit=env.settings.youtube_daily_units,
        )
    if not reserved:
        raise JobFailure(
            "YOUTUBE_DAILY_LIMIT",
            "Video suggestions have reached today's limit on this server. "
            "Please try again tomorrow.",
        )


async def _call[T](request: Awaitable[T]) -> T:
    try:
        return await request
    except YouTubeError as error:
        log.warning(
            "videos.youtube_error", code=error.code, retryable=error.retryable, detail=error.detail
        )
        raise JobFailure(error.code, error.message, retryable=error.retryable) from None
