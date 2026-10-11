"""Business rules for learning goals.

The status lifecycle, the archive-before-delete rule and "archived goals are read-only" are
enforced here first (with friendly errors) and again by database triggers and policies, so a bug
in this module still cannot store an illegal state.
"""

from collections.abc import Sequence
from typing import Final
from uuid import UUID

import psycopg.errors
import structlog

from app.core.db import UserConnection
from app.core.errors import (
    AuthenticationError,
    ConflictError,
    FieldError,
    InvalidRequestError,
    NotFoundError,
)
from app.core.pagination import decode_cursor, encode_cursor
from app.core.security import Principal
from app.repositories import goals as goals_repo
from app.repositories import profiles as profiles_repo
from app.schemas.goals import (
    Goal,
    GoalCreate,
    GoalPage,
    GoalStatus,
    GoalSummary,
    GoalUpdate,
    check_target_date,
)

log = structlog.get_logger("app.goals")

# Mirrors the database trigger. Same-state requests are handled before this table is consulted.
ALLOWED_TRANSITIONS: Final[frozenset[tuple[GoalStatus, GoalStatus]]] = frozenset(
    {
        ("active", "paused"),
        ("active", "completed"),
        ("active", "archived"),
        ("paused", "active"),
        ("paused", "completed"),
        ("paused", "archived"),
        ("completed", "active"),
        ("completed", "archived"),
        ("archived", "active"),
    }
)

_NEXT_STEP: Final[dict[GoalStatus, str]] = {
    "completed": "Reopen it first.",
    "archived": "Restore it first.",
    "paused": "Resume it first.",
    "active": "",
}


def _account_gone() -> AuthenticationError:
    return AuthenticationError(
        "This account no longer exists. Sign in again.", code="ACCOUNT_NOT_FOUND"
    )


def _not_found() -> NotFoundError:
    # Same answer for "does not exist" and "belongs to someone else": IDs cannot be probed.
    return NotFoundError("Goal not found.", code="GOAL_NOT_FOUND")


async def _own_goal(
    connection: UserConnection, principal: Principal, goal_id: UUID, *, for_update: bool = False
) -> Goal:
    goal = await goals_repo.get(connection, principal.user_id, goal_id, for_update=for_update)
    if goal is None:
        raise _not_found()
    return goal


async def _require_room(connection: UserConnection, principal: Principal, limit: int) -> None:
    if await goals_repo.count_not_archived(connection, principal.user_id) >= limit:
        raise ConflictError(
            f"You can have up to {limit} goals at once. Archive one to add another.",
            code="GOAL_LIMIT_REACHED",
        )


async def create_goal(
    connection: UserConnection,
    principal: Principal,
    payload: GoalCreate,
    *,
    max_active_goals: int,
) -> Goal:
    # The owner is always the verified caller; the request body has no way to name another user.
    await _require_room(connection, principal, max_active_goals)

    profile = await profiles_repo.get(connection, principal.user_id)
    if profile is None:
        log.warning("profile.missing")
        raise _account_gone()

    # Anything the request left out comes from the learner's saved preferences.
    daily_minutes = payload.daily_minutes or profile.default_daily_minutes
    languages = payload.preferred_languages or profile.preferred_languages
    practice = (
        payload.learning_preferences
        if payload.learning_preferences is not None
        else profile.learning_preferences
    )
    try:
        goal = await goals_repo.insert(
            connection,
            principal.user_id,
            payload,
            daily_minutes=daily_minutes,
            preferred_languages=languages,
            learning_preferences=list(practice),
        )
    except psycopg.errors.ForeignKeyViolation:
        # The only foreign key on insert is user_id -> profiles: the account no longer exists.
        raise _account_gone() from None
    # Identifiers only: goal titles and descriptions are user content and stay out of logs.
    log.info("goal.created", goal_id=str(goal.id))
    return goal


async def get_goal(connection: UserConnection, principal: Principal, goal_id: UUID) -> Goal:
    return await _own_goal(connection, principal, goal_id)


async def list_goals(
    connection: UserConnection,
    principal: Principal,
    *,
    statuses: Sequence[GoalStatus] | None,
    limit: int,
    cursor: str | None,
) -> GoalPage:
    after = decode_cursor(cursor) if cursor else None
    rows = await goals_repo.list_page(
        connection, principal.user_id, statuses=statuses, after=after, limit=limit + 1
    )
    page, has_more = rows[:limit], len(rows) > limit
    next_cursor = encode_cursor(page[-1].created_at, page[-1].id) if has_more else None
    return GoalPage(items=page, next_cursor=next_cursor)


async def summarize(connection: UserConnection, principal: Principal) -> GoalSummary:
    return await goals_repo.summary(connection, principal.user_id)


async def update_goal(
    connection: UserConnection, principal: Principal, goal_id: UUID, payload: GoalUpdate
) -> Goal:
    goal = await _own_goal(connection, principal, goal_id, for_update=True)
    if goal.status == "archived":
        raise ConflictError(
            "This goal is archived. Restore it before editing it.", code="GOAL_ARCHIVED"
        )

    # Keep only real changes: re-saving a form untouched must not bump updated_at.
    changes = {
        column: value
        for column, value in payload.changes().items()
        if value != getattr(goal, column)
    }
    new_date = changes.get("target_date")
    if new_date is not None and (problem := check_target_date(new_date)):
        # Only a changed date is checked, so a goal whose date has passed can still be renamed.
        raise InvalidRequestError(
            "The request contains invalid data.",
            code="VALIDATION_ERROR",
            errors=[FieldError(field="body.target_date", message=problem, code="value_error")],
        )
    if not changes:
        return goal

    updated = await goals_repo.update_fields(connection, principal.user_id, goal_id, changes)
    if updated is None:  # the row vanished between the lock and the update
        raise _not_found()
    log.info("goal.updated", goal_id=str(goal_id), fields=sorted(changes))
    return updated


async def change_status(
    connection: UserConnection,
    principal: Principal,
    goal_id: UUID,
    target: GoalStatus,
    *,
    max_active_goals: int,
) -> Goal:
    goal = await _own_goal(connection, principal, goal_id, for_update=True)
    if goal.status == target:
        return goal  # asking for the state it is already in is not an error

    if (goal.status, target) not in ALLOWED_TRANSITIONS:
        hint = _NEXT_STEP[goal.status]
        raise ConflictError(
            f"A goal that is {goal.status} can't be changed to {target}. {hint}".strip(),
            code="INVALID_STATUS_TRANSITION",
        )
    if goal.status == "archived":
        await _require_room(connection, principal, max_active_goals)  # restoring adds a live goal

    try:
        updated = await goals_repo.set_status(connection, principal.user_id, goal_id, target)
    except psycopg.errors.CheckViolation:
        raise ConflictError(
            "That status change isn't allowed right now.", code="INVALID_STATUS_TRANSITION"
        ) from None
    if updated is None:
        raise _not_found()
    log.info("goal.status_changed", goal_id=str(goal_id), from_status=goal.status, to_status=target)
    return updated


async def delete_goal(connection: UserConnection, principal: Principal, goal_id: UUID) -> None:
    goal = await _own_goal(connection, principal, goal_id, for_update=True)
    if goal.status != "archived":
        raise ConflictError(
            "Archive this goal before deleting it permanently.", code="GOAL_NOT_ARCHIVED"
        )
    if not await goals_repo.delete(connection, principal.user_id, goal_id):
        raise _not_found()
    log.info("goal.deleted", goal_id=str(goal_id))
