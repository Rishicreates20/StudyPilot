from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response

from app.api.deps import DatabaseDep
from app.core.errors import ProblemDetail
from app.core.security import CurrentPrincipal
from app.schemas.goals import Goal, GoalCreate, GoalPage, GoalStatus
from app.services import goals as goals_service

router = APIRouter(prefix="/goals", tags=["goals"])


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
    """Creates a goal owned by the caller. The owner is never taken from the request body."""
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
        GoalStatus | None,
        Query(description="Only goals with this status. Omit to list every goal except archived."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    cursor: Annotated[
        str | None, Query(max_length=200, description="From a previous page.")
    ] = None,
) -> GoalPage:
    async with database.user_transaction(principal) as connection:
        return await goals_service.list_goals(
            connection, principal, status=status, limit=limit, cursor=cursor
        )


@router.get(
    "/{goal_id}",
    response_model=Goal,
    summary="Read one of the caller's goals",
    responses={404: {"model": ProblemDetail, "description": "No such goal for this user"}},
)
async def read_goal(goal_id: UUID, principal: CurrentPrincipal, database: DatabaseDep) -> Goal:
    async with database.user_transaction(principal) as connection:
        return await goals_service.get_goal(connection, principal, goal_id)
