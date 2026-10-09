"""Business rules for learning goals."""

from uuid import UUID

import psycopg.errors
import structlog

from app.core.db import UserConnection
from app.core.errors import AuthenticationError, ConflictError, NotFoundError
from app.core.pagination import decode_cursor, encode_cursor
from app.core.security import Principal
from app.repositories import goals as goals_repo
from app.schemas.goals import Goal, GoalCreate, GoalPage, GoalStatus

log = structlog.get_logger("app.goals")


async def create_goal(
    connection: UserConnection,
    principal: Principal,
    payload: GoalCreate,
    *,
    max_active_goals: int,
) -> Goal:
    # The owner is always the verified caller; the request body has no way to name another user.
    active = await goals_repo.count_not_archived(connection, principal.user_id)
    if active >= max_active_goals:
        raise ConflictError(
            f"You can have up to {max_active_goals} goals at once. Archive one to add another.",
            code="GOAL_LIMIT_REACHED",
        )
    try:
        goal = await goals_repo.insert(connection, principal.user_id, payload)
    except psycopg.errors.ForeignKeyViolation:
        # The only foreign key on insert is user_id -> profiles: the account no longer exists.
        raise AuthenticationError(
            "This account no longer exists. Sign in again.", code="ACCOUNT_NOT_FOUND"
        ) from None
    # Identifiers only: goal titles and descriptions are user content and stay out of logs.
    log.info("goal.created", goal_id=str(goal.id))
    return goal


async def get_goal(connection: UserConnection, principal: Principal, goal_id: UUID) -> Goal:
    goal = await goals_repo.get(connection, principal.user_id, goal_id)
    if goal is None:
        # Same answer for "does not exist" and "belongs to someone else": IDs cannot be probed.
        raise NotFoundError("Goal not found.", code="GOAL_NOT_FOUND")
    return goal


async def list_goals(
    connection: UserConnection,
    principal: Principal,
    *,
    status: GoalStatus | None,
    limit: int,
    cursor: str | None,
) -> GoalPage:
    after = decode_cursor(cursor) if cursor else None
    rows = await goals_repo.list_page(
        connection, principal.user_id, status=status, after=after, limit=limit + 1
    )
    page, has_more = rows[:limit], len(rows) > limit
    next_cursor = encode_cursor(page[-1].created_at, page[-1].id) if has_more else None
    return GoalPage(items=page, next_cursor=next_cursor)
