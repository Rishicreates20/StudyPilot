"""SQL for profiles and their preferences. Same rules as the goals repository."""

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from psycopg import sql

from app.core.db import UserConnection
from app.schemas.profile import ProfileRow

_COLUMNS = """
    id, display_name, locale, timezone, onboarding_completed_at, default_daily_minutes,
    preferred_languages, learning_preferences, created_at
"""

# Profile settings a client may change. onboarding_completed_at has its own function.
EDITABLE_COLUMNS = frozenset(
    {
        "display_name",
        "locale",
        "timezone",
        "default_daily_minutes",
        "preferred_languages",
        "learning_preferences",
    }
)


async def get(connection: UserConnection, user_id: UUID) -> ProfileRow | None:
    cursor = await connection.execute(
        f"select {_COLUMNS} from public.profiles where id = %s",  # noqa: S608 - module constant
        (user_id,),
    )
    row = await cursor.fetchone()
    return ProfileRow.model_validate(row) if row else None


async def update_fields(
    connection: UserConnection, user_id: UUID, changes: Mapping[str, Any]
) -> ProfileRow | None:
    unknown = set(changes) - EDITABLE_COLUMNS
    if not changes or unknown:
        raise ValueError(f"not editable: {sorted(unknown) or 'nothing to change'}")
    assignments = sql.SQL(", ").join(
        sql.SQL("{} = {}").format(sql.Identifier(column), sql.Placeholder(column))
        for column in changes
    )
    query = sql.SQL(
        "update public.profiles set {assignments} where id = %(user_id)s returning {columns}"
    ).format(assignments=assignments, columns=sql.SQL(_COLUMNS))
    cursor = await connection.execute(query, {**changes, "user_id": user_id})
    row = await cursor.fetchone()
    return ProfileRow.model_validate(row) if row else None


async def complete_onboarding(connection: UserConnection, user_id: UUID) -> ProfileRow | None:
    """Mark onboarding finished. Idempotent: the first completion time is kept."""
    cursor = await connection.execute(
        "update public.profiles"  # noqa: S608 - _COLUMNS is a module constant
        " set onboarding_completed_at = coalesce(onboarding_completed_at, now())"
        f" where id = %s returning {_COLUMNS}",
        (user_id,),
    )
    row = await cursor.fetchone()
    return ProfileRow.model_validate(row) if row else None
