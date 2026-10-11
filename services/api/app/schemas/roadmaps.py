"""Request and response contracts for roadmap generation, jobs and roadmap versions.

Responses never include the model's raw output, prompts or provider details: only the stored,
validated plan and a job's learner-safe status. Requests reject unknown fields, so a body that
tries to name an owner or a status is a validation error.
"""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.ai.roadmap.schema import SyllabusBasis
from app.schemas.lessons import ItemStudy

RoadmapStatus = Literal["current", "superseded"]
ItemKind = Literal["topic", "revision", "enrichment"]

MAX_FEEDBACK_CHARS = 500


class RoadmapRequest(BaseModel):
    """Start generating a roadmap, optionally asking for changes to the current one."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    feedback: str | None = Field(
        default=None,
        max_length=MAX_FEEDBACK_CHARS,
        description=(
            "What to change about the current roadmap (for example 'fewer topics, more practice'). "
            "Leave out to generate a fresh plan."
        ),
    )

    @field_validator("feedback")
    @classmethod
    def _blank_is_none(cls, value: str | None) -> str | None:
        return value or None


class Objective(BaseModel):
    id: str
    text: str


class RoadmapItem(BaseModel):
    """A topic, a revision session or an optional enrichment topic."""

    id: UUID
    kind: ItemKind
    position: int
    key: str
    title: str
    description: str
    practice_task: str | None
    objective_ids: list[str]
    estimated_minutes: int
    # None for enrichment, which is not scheduled.
    day_number: int | None
    # Items that come first: earlier topics for a topic, the topics revisited for a revision.
    prerequisite_ids: list[UUID]
    # How far the learner has got with this item's lesson. Revision sessions have no lesson.
    study: ItemStudy


class RoadmapModule(BaseModel):
    id: UUID
    position: int
    title: str
    summary: str
    topics: list[RoadmapItem]


class RoadmapSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    goal_id: UUID
    version: int
    status: RoadmapStatus
    title: str
    language: str
    topic_count: int
    # Computed by the server from the stored items, never taken from the model.
    total_minutes: int
    total_days: int
    # The constraints this version was planned for.
    daily_minutes: int
    target_date: date | None
    revision_feedback: str | None
    based_on_roadmap_id: UUID | None
    # True when a test double, not an AI model, produced the content. Show it as a sample.
    is_synthetic: bool
    # Topics (not revision sessions or extras) whose lesson the learner has finished.
    completed_topics: int
    created_at: datetime


class Roadmap(RoadmapSummary):
    overview: str
    target_outcome: str
    # Where the plan's content comes from. Never presented as an official syllabus unless a real
    # uploaded document backs it.
    syllabus_basis: SyllabusBasis
    assumptions: list[str]
    unknowns: list[str]
    objectives: list[Objective]
    prompt_version: str
    modules: list[RoadmapModule]
    revision_sessions: list[RoadmapItem]
    enrichment: list[RoadmapItem]


class RoadmapList(BaseModel):
    # Newest version first.
    items: list[RoadmapSummary]
    current_id: UUID | None
