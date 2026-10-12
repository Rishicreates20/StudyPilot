"""Request and response contracts for lessons, the study workspace and study progress.

Lesson content is the typed ``Lesson`` document (see ``app.ai.lesson.schema``), never a string.
Responses carry the lesson's generation metadata so the screen can say where it came from, but
never the prompt, the model's raw output or provider details. Requests reject unknown fields, so a
body that tries to name an owner or a status is a validation error.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.ai.lesson.schema import Adjust, Lesson
from app.schemas.jobs import GenerationJob

LessonStatus = Literal["current", "superseded"]
StudyStatus = Literal["not_started", "in_progress", "completed"]
TopicKind = Literal["topic", "revision", "enrichment"]

MAX_LESSON_FEEDBACK_CHARS = 300
MAX_SECTIONS_PER_PROGRESS = 12


class LessonRequest(BaseModel):
    """Start writing the lesson for a topic, or ask for a different version of it."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    adjust: Adjust | None = Field(
        default=None,
        description=(
            "How the new version should differ from the current one: `simpler` (plainer words), "
            "`more_examples`, or `deeper`. Implies `regenerate`."
        ),
    )
    feedback: str | None = Field(
        default=None,
        max_length=MAX_LESSON_FEEDBACK_CHARS,
        description="What to change, in the learner's words. Implies `regenerate`.",
    )
    regenerate: bool = Field(
        default=False,
        description="Write a new version even though the topic already has a lesson.",
    )

    @field_validator("feedback")
    @classmethod
    def _blank_is_none(cls, value: str | None) -> str | None:
        return value or None


class ItemStudy(BaseModel):
    """How far a learner has got with one roadmap item's lesson."""

    status: StudyStatus
    has_lesson: bool
    # Sections finished in the lesson version they are on, and how many it has.
    sections_done: int
    sections_total: int


class LessonVersion(BaseModel):
    """A stored version of a topic's lesson, without its content."""

    id: UUID
    version: int
    status: LessonStatus
    title: str
    adjust: Adjust | None
    is_synthetic: bool
    created_at: datetime


class Citation(BaseModel):
    """A lesson's pointer to a passage of the learner's own document, looked up as it is now.

    Stored lessons keep only the document and passage ids. Here they are resolved against what
    still exists, so a citation to a document the learner later deleted is shown as unavailable
    instead of keeping a copy of the document's text alive.
    """

    source_id: str
    chunk_id: str
    note: str | None
    available: bool
    document_id: UUID | None = None
    document_title: str | None = None
    # "p. 3", "pp. 3 to 4" or "part 2".
    position: str | None = None
    page_start: int | None = None
    excerpt: str | None = None


class LessonDetail(LessonVersion):
    """One version of a lesson with its content and how it was made."""

    item_id: UUID
    language: str
    content: Lesson
    # The version of the content format, so older lessons stay readable if it changes.
    content_version: int
    revision_feedback: str | None
    based_on_lesson_id: UUID | None
    prompt_version: str
    provider: str
    model_id: str
    # One entry per source the lesson cites, in citation order (empty for an ungrounded lesson).
    citations: list[Citation] = Field(default_factory=list[Citation])


class ProgressState(BaseModel):
    lesson_id: UUID
    status: Literal["in_progress", "completed"]
    completed_section_ids: list[str]
    # Where to resume: the section the learner was reading.
    current_section_id: str | None
    started_at: datetime
    last_studied_at: datetime
    completed_at: datetime | None


class ProgressUpdate(BaseModel):
    """The learner's whole place in a lesson. Saving replaces what was saved before."""

    model_config = ConfigDict(extra="forbid")

    completed_section_ids: list[str] = Field(
        default_factory=list[str], max_length=MAX_SECTIONS_PER_PROGRESS
    )
    current_section_id: str | None = Field(default=None, pattern=r"^s[0-9]{1,2}$")
    completed: bool = Field(
        default=False,
        description="Finish the lesson. Every section is then recorded as done.",
    )


class TopicInfo(BaseModel):
    """The roadmap topic a lesson belongs to."""

    id: UUID
    goal_id: UUID
    roadmap_id: UUID
    key: str
    kind: TopicKind
    title: str
    description: str
    practice_task: str | None
    estimated_minutes: int
    day_number: int | None
    module_title: str | None


class StudyRoadmap(BaseModel):
    id: UUID
    version: int
    status: LessonStatus
    title: str


class NeighbourTopic(BaseModel):
    id: UUID
    title: str


class OutlineEntry(BaseModel):
    """One topic in the contents panel."""

    item_id: UUID
    key: str
    title: str
    kind: TopicKind
    module_title: str | None
    estimated_minutes: int
    study: ItemStudy


class StudyView(BaseModel):
    """Everything the study page shows for one topic, in one response."""

    topic: TopicInfo
    roadmap: StudyRoadmap
    # The lesson being shown: the current version, or the one asked for. None before one exists.
    lesson: LessonDetail | None
    versions: list[LessonVersion]
    progress: ProgressState | None
    # The newest lesson job for this topic (writing now, or the last failure).
    job: GenerationJob | None
    previous: NeighbourTopic | None
    next: NeighbourTopic | None
    outline: list[OutlineEntry]
    goal_archived: bool
    # Whether a lesson can be written now: the roadmap is the current one, the goal is not archived,
    # and the topic is not a revision session.
    can_generate: bool
