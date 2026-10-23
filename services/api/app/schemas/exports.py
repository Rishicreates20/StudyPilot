"""Request and response contracts for exported files (PDF notes, revision sheets, roadmaps, slides).

An export never exposes where its file is stored or the upload capability the worker uses; a
download is a short-lived link minted on request. Requests reject unknown fields, so a body that
tries to name an owner, a goal or a file is a validation error.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.exports.model import ExportFormat
from app.schemas.jobs import GenerationJob

# `ready`: the file can be downloaded. `processing`: a job is queued or running. `failed`: the last
# job ended without a file (ask again to retry). `not_started`: no job was ever queued.
ExportStatus = Literal["ready", "processing", "failed", "not_started"]
LessonExportFormat = Literal["notes_pdf", "revision_pdf", "slides_pptx"]
RoadmapExportFormat = Literal["roadmap_pdf", "slides_pptx"]


class LessonExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: LessonExportFormat = Field(
        description="`notes_pdf` (the whole lesson), `revision_pdf` (a one-to-two page sheet) or "
        "`slides_pptx` (a PowerPoint deck)."
    )


class RoadmapExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: RoadmapExportFormat = Field(
        description="`roadmap_pdf` (the plan with its schedule) or `slides_pptx`."
    )


class Export(BaseModel):
    id: UUID
    goal_id: UUID
    # Exactly one of these names the source.
    lesson_id: UUID | None
    roadmap_id: UUID | None
    # The title and version of the lesson or roadmap the file is made from.
    source_title: str
    source_version: int
    format: ExportFormat
    template_version: str
    status: ExportStatus
    # Set once the file is ready.
    file_name: str | None
    content_type: str | None
    size_bytes: int | None
    # Pages of a PDF, or slides of a presentation.
    page_count: int | None
    # Characters no embedded font could show (printed as a replacement mark). Always 0 for slides,
    # which use the viewer's fonts.
    unsupported_characters: int | None
    ready_at: datetime | None
    created_at: datetime
    # The newest job for this export, if any: its status, stage and any learner-safe error.
    job: GenerationJob | None


class ExportList(BaseModel):
    items: list[Export]


class DownloadLink(BaseModel):
    """Where to fetch the file. ``url`` is a signed link valid until ``expires_at``; it is null
    when the server keeps files on its own disk (development), and the file is then served by
    ``GET /v1/exports/{id}/file``."""

    url: str | None
    expires_at: datetime | None
    file_name: str
