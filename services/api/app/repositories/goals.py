"""SQL for learning goals. Data access only: no business rules, no HTTP concerns.

Every function takes a ``UserConnection`` (already restricted to the caller by Row Level Security)
AND filters by ``user_id`` explicitly, so ownership does not rest on either layer alone.
Values are always bound parameters; SQL text never contains caller input.
"""

from datetime import datetime
from uuid import UUID

from app.core.db import UserConnection
from app.schemas.goals import Goal, GoalCreate, GoalStatus

_COLUMNS = """
    id, title, description, goal_type, current_level, target_date, daily_minutes,
    preferred_languages, status, created_at, updated_at
"""


async def insert(connection: UserConnection, user_id: UUID, payload: GoalCreate) -> Goal:
    cursor = await connection.execute(
        f"""
        insert into public.learning_goals
            (user_id, title, description, goal_type, current_level, target_date, daily_minutes,
             preferred_languages)
        values
            (%(user_id)s, %(title)s, %(description)s, %(goal_type)s, %(current_level)s,
             %(target_date)s, %(daily_minutes)s, %(preferred_languages)s)
        returning {_COLUMNS}
        """,  # noqa: S608 - _COLUMNS is a module constant, not caller input
        {
            "user_id": user_id,
            "title": payload.title,
            "description": payload.description,
            "goal_type": payload.goal_type,
            "current_level": payload.current_level,
            "target_date": payload.target_date,
            "daily_minutes": payload.daily_minutes,
            "preferred_languages": payload.preferred_languages,
        },
    )
    row = await cursor.fetchone()
    if row is None:  # an INSERT ... RETURNING always yields a row unless RLS blocked it
        raise RuntimeError("insert returned no row")
    return Goal.model_validate(row)


async def get(connection: UserConnection, user_id: UUID, goal_id: UUID) -> Goal | None:
    cursor = await connection.execute(
        f"select {_COLUMNS} from public.learning_goals where id = %s and user_id = %s",  # noqa: S608
        (goal_id, user_id),
    )
    row = await cursor.fetchone()
    return Goal.model_validate(row) if row else None


async def list_page(
    connection: UserConnection,
    user_id: UUID,
    *,
    status: GoalStatus | None,
    after: tuple[datetime, UUID] | None,
    limit: int,
) -> list[Goal]:
    """Newest first. Fetches ``limit`` rows; the caller asks for one extra to detect a next page."""
    cursor = await connection.execute(
        f"""
        select {_COLUMNS}
        from public.learning_goals
        where user_id = %(user_id)s
          and (case when %(status)s::text is null then status <> 'archived'
                    else status = %(status)s::text end)
          and (%(after_created_at)s::timestamptz is null
               or (created_at, id) < (%(after_created_at)s::timestamptz, %(after_id)s::uuid))
        order by created_at desc, id desc
        limit %(limit)s
        """,  # noqa: S608
        {
            "user_id": user_id,
            "status": status,
            "after_created_at": after[0] if after else None,
            "after_id": after[1] if after else None,
            "limit": limit,
        },
    )
    return [Goal.model_validate(row) for row in await cursor.fetchall()]


async def count_not_archived(connection: UserConnection, user_id: UUID) -> int:
    cursor = await connection.execute(
        "select count(*) as total from public.learning_goals"
        " where user_id = %s and status <> 'archived'",
        (user_id,),
    )
    row = await cursor.fetchone()
    return int(row["total"]) if row else 0
