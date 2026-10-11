"""Business rules for generating roadmaps, following their jobs, and switching versions.

The API never runs the model. Starting a generation only validates the request and queues a job
(in the caller's own transaction); the worker does the rest. Every rule here that protects money
or data (one generation at a time per goal, a daily allowance, archived goals are read-only) is
also backed by the database where it can be.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import psycopg.errors
import structlog

from app.ai.roadmap.context import readiness_problems
from app.core.config import Settings
from app.core.db import UserConnection
from app.core.errors import (
    ConflictError,
    InvalidRequestError,
    NotFoundError,
    RateLimitedError,
    ServiceUnavailableError,
)
from app.core.security import Principal
from app.repositories import goals as goals_repo
from app.repositories import jobs as jobs_repo
from app.repositories import roadmaps as roadmaps_repo
from app.schemas.goals import Goal, today_utc
from app.schemas.jobs import GenerationJob, JobList
from app.schemas.roadmaps import Roadmap, RoadmapList, RoadmapRequest, RoadmapSummary

log = structlog.get_logger("app.roadmaps")

_ALLOWANCE_WINDOW = timedelta(hours=24)


def _goal_not_found() -> NotFoundError:
    # Same answer for "does not exist" and "belongs to someone else".
    return NotFoundError("Goal not found.", code="GOAL_NOT_FOUND")


def _roadmap_not_found() -> NotFoundError:
    return NotFoundError("Roadmap not found.", code="ROADMAP_NOT_FOUND")


def _archived() -> ConflictError:
    return ConflictError(
        "This goal is archived. Restore it to work with its roadmap.", code="GOAL_ARCHIVED"
    )


async def _own_goal(
    connection: UserConnection, principal: Principal, goal_id: UUID, *, for_update: bool = False
) -> Goal:
    goal = await goals_repo.get(connection, principal.user_id, goal_id, for_update=for_update)
    if goal is None:
        raise _goal_not_found()
    return goal


async def start_generation(
    connection: UserConnection,
    principal: Principal,
    goal_id: UUID,
    payload: RoadmapRequest,
    *,
    idempotency_key: str | None,
    settings: Settings,
) -> GenerationJob:
    """Queue a roadmap generation for one of the caller's goals."""
    if not settings.ai_configured:
        raise ServiceUnavailableError(
            "AI roadmap generation isn't set up on this server yet.", code="AI_NOT_CONFIGURED"
        )
    # Locking the goal row serialises concurrent starts for it (two tabs, a double click).
    goal = await _own_goal(connection, principal, goal_id, for_update=True)

    request: dict[str, Any] = {}
    if payload.feedback:
        request["feedback"] = payload.feedback
        current_id = await roadmaps_repo.get_current_id(connection, principal.user_id, goal_id)
        if current_id is not None:
            request["base_roadmap_id"] = str(current_id)

    if idempotency_key:
        existing = await jobs_repo.find_by_idempotency_key(
            connection, principal.user_id, idempotency_key
        )
        if existing is not None:
            stored = await jobs_repo.get_request(connection, principal.user_id, existing.id)
            same = (
                existing.job_type == "roadmap"
                and existing.goal_id == goal_id
                and (stored or {}).get("feedback") == request.get("feedback")
            )
            if same:
                return existing  # the same form submitted twice: same job
            raise ConflictError(
                "That Idempotency-Key was already used for a different request.",
                code="IDEMPOTENCY_KEY_REUSED",
            )

    if goal.status == "archived":
        raise _archived()
    if problems := readiness_problems(goal, today_utc()):
        raise InvalidRequestError(problems[0], code="GOAL_NOT_PLANNABLE")
    if await jobs_repo.active_for_goal(connection, principal.user_id, goal_id) is not None:
        raise ConflictError(
            "A roadmap is already being generated for this goal.", code="ROADMAP_JOB_ACTIVE"
        )
    allowance = settings.roadmap_jobs_per_user_per_day
    since = datetime.now(UTC) - _ALLOWANCE_WINDOW
    if await jobs_repo.count_since(connection, principal.user_id, since) >= allowance:
        raise RateLimitedError(
            f"You can generate up to {allowance} roadmaps a day. Please try again tomorrow.",
            code="GENERATION_LIMIT_REACHED",
        )

    try:
        job = await jobs_repo.insert(
            connection,
            principal.user_id,
            goal_id,
            idempotency_key=idempotency_key,
            request=request,
        )
    except psycopg.errors.UniqueViolation:
        # Lost a race the lock above should already prevent; the database index is the backstop.
        raise ConflictError(
            "A roadmap is already being generated for this goal.", code="ROADMAP_JOB_ACTIVE"
        ) from None
    # Identifiers only: goal text and feedback are user content and stay out of logs.
    log.info(
        "roadmap.requested",
        job_id=str(job.id),
        goal_id=str(goal_id),
        revising="feedback" in request,
    )
    return job


async def list_versions(
    connection: UserConnection, principal: Principal, goal_id: UUID
) -> RoadmapList:
    await _own_goal(connection, principal, goal_id)
    versions = await roadmaps_repo.list_versions(connection, principal.user_id, goal_id)
    current = next((v.id for v in versions if v.status == "current"), None)
    return RoadmapList(items=versions, current_id=current)


async def get_roadmap(
    connection: UserConnection, principal: Principal, roadmap_id: UUID
) -> Roadmap:
    roadmap = await roadmaps_repo.get_detail(connection, principal.user_id, roadmap_id)
    if roadmap is None:
        raise _roadmap_not_found()
    return roadmap


async def make_current(
    connection: UserConnection, principal: Principal, roadmap_id: UUID
) -> RoadmapSummary:
    """Make an earlier (or any) version the goal's current plan. Nothing is deleted."""
    summary = await roadmaps_repo.get_summary(connection, principal.user_id, roadmap_id)
    if summary is None:
        raise _roadmap_not_found()
    goal = await _own_goal(connection, principal, summary.goal_id, for_update=True)
    if goal.status == "archived":
        raise _archived()
    if summary.status != "current":
        await roadmaps_repo.make_current(connection, principal.user_id, goal.id, roadmap_id)
        log.info("roadmap.version_switched", goal_id=str(goal.id), version=summary.version)
    switched = await roadmaps_repo.get_summary(connection, principal.user_id, roadmap_id)
    if switched is None:
        raise _roadmap_not_found()
    return switched


async def list_jobs(
    connection: UserConnection, principal: Principal, goal_id: UUID, *, limit: int
) -> JobList:
    await _own_goal(connection, principal, goal_id)
    jobs = await jobs_repo.list_for_goal(connection, principal.user_id, goal_id, limit=limit)
    return JobList(items=jobs)
