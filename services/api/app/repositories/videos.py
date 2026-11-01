"""SQL for a learner's own video suggestions. Read only: only the worker writes these tables."""

from uuid import UUID

from app.core.db import UserConnection
from app.schemas.videos import TopicVideo, VideoSearchInfo


async def get_search(
    connection: UserConnection, user_id: UUID, item_id: UUID
) -> VideoSearchInfo | None:
    cursor = await connection.execute(
        "select id, queries, languages, candidates_seen, result_count, searched_at,"
        " last_verified_at from public.resource_searches"
        " where item_id = %s and user_id = %s",
        (item_id, user_id),
    )
    row = await cursor.fetchone()
    return VideoSearchInfo.model_validate(row) if row else None


async def list_videos(connection: UserConnection, user_id: UUID, item_id: UUID) -> list[TopicVideo]:
    """The topic's suggestions that are still watchable, best first."""
    cursor = await connection.execute(
        "select id, external_id as video_id, url, title, channel_title, duration_seconds,"
        " published_at, language, language_source, searched_language, thumbnail_url,"
        " thumbnail_width, thumbnail_height, view_count, relevance_score, score_basis, position,"
        " last_verified_at"
        " from public.topic_resources"
        " where item_id = %s and user_id = %s and status = 'available'"
        " order by position",
        (item_id, user_id),
    )
    return [TopicVideo.model_validate(row) for row in await cursor.fetchall()]
