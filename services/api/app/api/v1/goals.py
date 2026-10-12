from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response

from app.api.deps import DatabaseDep, FilesDep
from app.core.errors import ProblemDetail
from app.core.security import AccessToken, CurrentPrincipal
from app.schemas.goals import (
    Goal,
    GoalCreate,
    GoalPage,
    GoalStatus,
    GoalStatusChange,
    GoalSummary,
    GoalUpdate,
)
from app.services import documents as documents_service
from app.services import goals as goals_service

router = APIRouter(prefix="/goals", tags=["goals"])

_NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {"model": ProblemDetail, "description": "No such goal for this user"}
}


@router.post(
    "",
    response_model=Goal,
    status_code=201,
    summary="Create a learning goal",
    responses={409: {"model": ProblemDetail, "description": "Goal limit reached"}},
)
async def create_goal(
    payload: GoalCreate,
    request: Request,
    response: Response,
    principal: CurrentPrincipal,
    database: DatabaseDep,
) -> Goal:
    """Creates a goal owned by the caller. The owner is never taken from the request body.

    Settings left out of the body (daily minutes, languages, kinds of practice) come from the
    caller's saved preferences.
    """
    max_goals = request.app.state.settings.max_active_goals_per_user
    async with database.user_transaction(principal) as connection:
        goal = await goals_service.create_goal(
            connection, principal, payload, max_active_goals=max_goals
        )
    response.headers["Location"] = f"/v1/goals/{goal.id}"
    return goal


@router.get("", response_model=GoalPage, summary="List the caller's goals, newest first")
async def list_goals(
    principal: CurrentPrincipal,
    database: DatabaseDep,
    status: Annotated[
        list[GoalStatus] | None,
        Query(
            description=(
                "Only goals in these states (repeat the parameter for several). "
                "Omit to list every goal except archived ones."
            )
        ),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    cursor: Annotated[
        str | None, Query(max_length=200, description="From a previous page.")
    ] = None,
) -> GoalPage:
    async with database.user_transaction(principal) as connection:
        return await goals_service.list_goals(
            connection, principal, statuses=status, limit=limit, cursor=cursor
        )


# Declared before "/{goal_id}" so that "summary" is never parsed as a goal ID.
@router.get("/summary", response_model=GoalSummary, summary="How many goals are in each state")
async def goal_summary(principal: CurrentPrincipal, database: DatabaseDep) -> GoalSummary:
    async with database.user_transaction(principal) as connection:
        return await goals_service.summarize(connection, principal)


@router.get(
    "/{goal_id}",
    response_model=Goal,
    summary="Read one of the caller's goals",
    responses=_NOT_FOUND,
)
async def read_goal(goal_id: UUID, principal: CurrentPrincipal, database: DatabaseDep) -> Goal:
    async with database.user_transaction(principal) as connection:
        return await goals_service.get_goal(connection, principal, goal_id)


@router.patch(
    "/{goal_id}",
    response_model=Goal,
    summary="Edit one of the caller's goals",
    responses={
        **_NOT_FOUND,
        409: {"model": ProblemDetail, "description": "The goal is archived"},
    },
)
async def update_goal(
    goal_id: UUID, payload: GoalUpdate, principal: CurrentPrincipal, database: DatabaseDep
) -> Goal:
    """Changes only the fields sent. ``null`` clears the description or the target date."""
    async with database.user_transaction(principal) as connection:
        return await goals_service.update_goal(connection, principal, goal_id, payload)


@router.put(
    "/{goal_id}/status",
    response_model=Goal,
    summary="Pause, resume, complete, reopen, archive or restore a goal",
    responses={
        **_NOT_FOUND,
        409: {"model": ProblemDetail, "description": "That change isn't allowed from this state"},
    },
)
async def change_goal_status(
    goal_id: UUID,
    payload: GoalStatusChange,
    request: Request,
    principal: CurrentPrincipal,
    database: DatabaseDep,
) -> Goal:
    """Moves a goal along its lifecycle. Asking for the state it is already in changes nothing.

    Allowed: active ⇄ paused, active or paused → completed, completed → active (reopen),
    any open or completed goal → archived, archived → active (restore).
    """
    max_goals = request.app.state.settings.max_active_goals_per_user
    async with database.user_transaction(principal) as connection:
        return await goals_service.change_status(
            connection, principal, goal_id, payload.status, max_active_goals=max_goals
        )


@router.delete(
    "/{goal_id}",
    status_code=204,
    summary="Permanently delete an archived goal",
    responses={
        **_NOT_FOUND,
        409: {"model": ProblemDetail, "description": "Only archived goals can be deleted"},
    },
)
async def delete_goal(
    goal_id: UUID,
    principal: CurrentPrincipal,
    token: AccessToken,
    database: DatabaseDep,
    files: FilesDep,
) -> Response:
    """Also removes the goal's uploaded files from storage (its rows cascade)."""
    await documents_service.purge_goal_files(
        database, principal, token, files=files, goal_id=goal_id
    )
    async with database.user_transaction(principal) as connection:
        await goals_service.delete_goal(connection, principal, goal_id)
    return Response(status_code=204)
