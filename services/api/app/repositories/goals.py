"""SQL for learning goals. Data access only: no business rules, no HTTP concerns.

Every function takes a ``UserConnection`` (already restricted to the caller by Row Level Security)
AND filters by ``user_id`` explicitly, so ownership does not rest on either layer alone.
Values are always bound parameters. The only SQL text assembled at run time is the list of columns
in an UPDATE, and those names come from a fixed allow-list, never from the caller.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from psycopg import sql

from app.core.db import UserConnection
from app.schemas.goals import Goal, GoalCreate, GoalStatus, GoalSummary

_COLUMNS = """
    id, title, description, goal_type, current_level, target_date, daily_minutes,
    preferred_languages, learning_preferences, status, completed_at, archived_at,
    created_at, updated_at
"""

# The only columns an edit may set. Status has its own function; ids, owner and timestamps are
# never client-writable (the database grants don't allow it either).
EDITABLE_COLUMNS = frozenset(
    {
        "title",
        "description",
        "goal_type",
        "current_level",
        "target_date",
        "daily_minutes",
        "preferred_languages",
        "learning_preferences",
    }
)


async def insert(
    connection: UserConnection,
    user_id: UUID,
    payload: GoalCreate,
    *,
    daily_minutes: int,
    preferred_languages: list[str],
    learning_preferences: list[str],
) -> Goal:
    """Insert a goal. Settings the request left out are passed in already resolved."""
    cursor = await connection.execute(
        f"""
        insert into public.learning_goals
            (user_id, title, description, goal_type, current_level, target_date, daily_minutes,
             preferred_languages, learning_preferences)
        values
            (%(user_id)s, %(title)s, %(description)s, %(goal_type)s, %(current_level)s,
             %(target_date)s, %(daily_minutes)s, %(preferred_languages)s,
             %(learning_preferences)s)
        returning {_COLUMNS}
        """,  # noqa: S608 - _COLUMNS is a module constant, not caller input
        {
            "user_id": user_id,
            "title": payload.title,
            "description": payload.description,
            "goal_type": payload.goal_type,
            "current_level": payload.current_level,
            "target_date": payload.target_date,
            "daily_minutes": daily_minutes,
            "preferred_languages": preferred_languages,
            "learning_preferences": learning_preferences,
        },
    )
    row = await cursor.fetchone()
    if row is None:  # an INSERT ... RETURNING always yields a row unless RLS blocked it
        raise RuntimeError("insert returned no row")
    return Goal.model_validate(row)


async def get(
    connection: UserConnection, user_id: UUID, goal_id: UUID, *, for_update: bool = False
) -> Goal | None:
    """One of the caller's goals. ``for_update`` locks the row until the transaction ends, so a
    read-check-write sequence (a status change) cannot interleave with another request."""
    lock = " for update" if for_update else ""
    cursor = await connection.execute(
        f"select {_COLUMNS} from public.learning_goals where id = %s and user_id = %s{lock}",  # noqa: S608
        (goal_id, user_id),
    )
    row = await cursor.fetchone()
    return Goal.model_validate(row) if row else None


async def list_page(
    connection: UserConnection,
    user_id: UUID,
    *,
    statuses: Sequence[GoalStatus] | None,
    after: tuple[datetime, UUID] | None,
    limit: int,
) -> list[Goal]:
    """Newest first. Fetches ``limit`` rows; the caller asks for one extra to detect a next page.

    ``statuses=None`` means every goal except archived ones.
    """
    cursor = await connection.execute(
        f"""
        select {_COLUMNS}
        from public.learning_goals
        where user_id = %(user_id)s
          and (case when %(statuses)s::text[] is null then status <> 'archived'
                    else status = any(%(statuses)s::text[]) end)
          and (%(after_created_at)s::timestamptz is null
               or (created_at, id) < (%(after_created_at)s::timestamptz, %(after_id)s::uuid))
        order by created_at desc, id desc
        limit %(limit)s
        """,  # noqa: S608
        {
            "user_id": user_id,
            "statuses": list(statuses) if statuses else None,
            "after_created_at": after[0] if after else None,
            "after_id": after[1] if after else None,
            "limit": limit,
        },
    )
    return [Goal.model_validate(row) for row in await cursor.fetchall()]


async def update_fields(
    connection: UserConnection, user_id: UUID, goal_id: UUID, changes: Mapping[str, Any]
) -> Goal | None:
    """Set the given editable columns. Returns the goal, or None if it isn't the caller's."""
    unknown = set(changes) - EDITABLE_COLUMNS
    if not changes or unknown:
        raise ValueError(f"not editable: {sorted(unknown) or 'nothing to change'}")
    assignments = sql.SQL(", ").join(
        sql.SQL("{} = {}").format(sql.Identifier(column), sql.Placeholder(column))
        for column in changes
    )
    query = sql.SQL(
        "update public.learning_goals set {assignments}"
        " where id = %(goal_id)s and user_id = %(user_id)s returning {columns}"
    ).format(assignments=assignments, columns=sql.SQL(_COLUMNS))
    cursor = await connection.execute(query, {**changes, "goal_id": goal_id, "user_id": user_id})
    row = await cursor.fetchone()
    return Goal.model_validate(row) if row else None


async def set_status(
    connection: UserConnection, user_id: UUID, goal_id: UUID, status: GoalStatus
) -> Goal | None:
    """Change the status. The database stamps completed_at / archived_at and checks the move."""
    cursor = await connection.execute(
        f"update public.learning_goals set status = %s where id = %s and user_id = %s"  # noqa: S608
        f" returning {_COLUMNS}",
        (status, goal_id, user_id),
    )
    row = await cursor.fetchone()
    return Goal.model_validate(row) if row else None


async def delete(connection: UserConnection, user_id: UUID, goal_id: UUID) -> bool:
    """Delete a goal; True if a row went away. The database only allows archived goals."""
    cursor = await connection.execute(
        "delete from public.learning_goals where id = %s and user_id = %s", (goal_id, user_id)
    )
    return cursor.rowcount == 1


async def count_not_archived(connection: UserConnection, user_id: UUID) -> int:
    cursor = await connection.execute(
        "select count(*) as total from public.learning_goals"
        " where user_id = %s and status <> 'archived'",
        (user_id,),
    )
    row = await cursor.fetchone()
    return int(row["total"]) if row else 0


async def summary(connection: UserConnection, user_id: UUID) -> GoalSummary:
    cursor = await connection.execute(
        "select status, count(*) as total from public.learning_goals"
        " where user_id = %s group by status",
        (user_id,),
    )
    counts = {row["status"]: int(row["total"]) for row in await cursor.fetchall()}
    return GoalSummary(
        active=counts.get("active", 0),
        paused=counts.get("paused", 0),
        completed=counts.get("completed", 0),
        archived=counts.get("archived", 0),
    )
