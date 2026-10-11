"""What the planner is asked to produce: a learning roadmap, as validated data.

The field descriptions double as instructions to the model (they are sent with the schema). The
limits here only reject shapes that make no sense; the rules that depend on the learner (their
daily minutes, their target date, their objectives) live in ``validation.py``.

``extra="ignore"``: a model that adds a field we never asked for is harmless, because nothing it
adds is ever stored. A missing or mistyped field is not harmless and fails validation.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MAX_DAY = 366
MAX_MODULES = 12
MAX_TOPICS_PER_MODULE = 15
MAX_TOPICS = 80

SyllabusBasis = Literal["learner_stated", "uploaded_document", "general_knowledge"]


class _PlanModel(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


class PlanObjective(_PlanModel):
    id: str = Field(
        min_length=1,
        max_length=20,
        description='Short unique id such as "o1", "o2". Topics refer to objectives by this id.',
    )
    text: str = Field(
        min_length=5,
        max_length=300,
        description="One thing the learner will be able to do, starting with a verb.",
    )


class PlanTopic(_PlanModel):
    key: str = Field(
        min_length=2,
        max_length=48,
        description=(
            "Unique lowercase identifier made of letters, digits and hyphens, "
            'for example "pointers-and-memory".'
        ),
    )
    title: str = Field(min_length=2, max_length=120)
    description: str = Field(
        min_length=5, max_length=600, description="What is studied and why it matters here."
    )
    objective_ids: list[str] = Field(
        min_length=1,
        max_length=6,
        description="Ids of the objectives this topic helps achieve. At least one.",
    )
    prerequisite_keys: list[str] = Field(
        default_factory=list,
        max_length=6,
        description="Keys of topics that must be studied BEFORE this one. Only earlier topics.",
    )
    estimated_minutes: int = Field(
        ge=5, le=480, description="Study time for this topic in minutes. Fits in one day."
    )
    day: int = Field(
        ge=1, le=MAX_DAY, description="The study day (1 = first day) this topic is scheduled on."
    )
    practice_task: str = Field(
        min_length=5,
        max_length=400,
        description="A concrete exercise the learner does to practise this topic.",
    )


class PlanModule(_PlanModel):
    title: str = Field(min_length=2, max_length=120)
    summary: str = Field(min_length=5, max_length=500)
    topics: list[PlanTopic] = Field(
        min_length=1,
        max_length=MAX_TOPICS_PER_MODULE,
        description="Topics in the order they are studied.",
    )


class PlanRevision(_PlanModel):
    key: str = Field(
        min_length=2, max_length=48, description="Unique identifier, like a topic key."
    )
    title: str = Field(min_length=2, max_length=120)
    day: int = Field(ge=1, le=MAX_DAY, description="The day of this revision session.")
    estimated_minutes: int = Field(ge=5, le=240)
    revisits: list[str] = Field(
        min_length=1,
        max_length=10,
        description="Keys of the topics revised. Each must be scheduled on or before this day.",
    )
    task: str = Field(
        min_length=5,
        max_length=400,
        description="What the learner does: recall questions, a mixed exercise, a summary...",
    )


class PlanEnrichment(_PlanModel):
    key: str = Field(min_length=2, max_length=48, description="Unique identifier.")
    title: str = Field(min_length=2, max_length=120)
    description: str = Field(min_length=5, max_length=500)
    estimated_minutes: int = Field(ge=5, le=480)


class PlanEvidence(_PlanModel):
    """A pointer to the learner's uploaded material that supports the plan."""

    source_id: str = Field(min_length=1, max_length=64)
    chunk_id: str = Field(min_length=1, max_length=64)


class PlannedRoadmap(_PlanModel):
    language: str = Field(
        min_length=2,
        max_length=3,
        description="ISO code of the language the plan is written in. One of the learner's.",
    )
    title: str = Field(min_length=3, max_length=200)
    overview: str = Field(
        min_length=20, max_length=1500, description="A short summary of the whole plan."
    )
    target_outcome: str = Field(
        min_length=10, max_length=500, description="What the learner can do at the end."
    )
    syllabus_basis: SyllabusBasis = Field(
        description=(
            '"uploaded_document" only if learner material was supplied; "learner_stated" when '
            'the plan follows what the learner described; otherwise "general_knowledge".'
        )
    )
    assumptions: list[str] = Field(
        default_factory=list,
        max_length=8,
        description="Assumptions made where the learner's goal was not specific.",
    )
    unknowns: list[str] = Field(
        default_factory=list,
        max_length=8,
        description=(
            "Things the plan could not know, such as the official syllabus, exam pattern or "
            "dates, that the learner should confirm."
        ),
    )
    objectives: list[PlanObjective] = Field(min_length=1, max_length=12)
    modules: list[PlanModule] = Field(
        min_length=1, max_length=MAX_MODULES, description="Modules in the order they are studied."
    )
    revision_sessions: list[PlanRevision] = Field(default_factory=list[PlanRevision], max_length=12)
    enrichment: list[PlanEnrichment] = Field(
        default_factory=list[PlanEnrichment],
        max_length=6,
        description="Optional extra topics. They are not scheduled and not part of the time plan.",
    )
    evidence: list[PlanEvidence] = Field(default_factory=list[PlanEvidence], max_length=30)

    def topics(self) -> list[PlanTopic]:
        """Every topic in study order."""
        return [topic for module in self.modules for topic in module.topics]
