"""Background jobs as the API shows them: learner-safe status, never prompts or model output."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

JobStatus = Literal["queued", "running", "completed", "failed", "cancelled"]
# `resources` exists in the database (the recovered resources migration) but nothing in this
# repository creates or runs it yet; it is listed so such a row can still be shown.
JobType = Literal["roadmap", "lesson", "quiz", "grade", "document", "export", "resources"]


class GenerationJob(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    goal_id: UUID
    job_type: JobType
    # The roadmap topic a lesson job is writing for; None for roadmap jobs.
    item_id: UUID | None
    # The quiz attempt a grading job marks; None for every other kind of job.
    attempt_id: UUID | None
    # The document a document job processes; None for every other kind of job.
    document_id: UUID | None
    # The export an export job renders; None for every other kind of job.
    export_id: UUID | None = None
    status: JobStatus
    # Where the job is: queued, starting, loading, planning or writing, validated, saving,
    # waiting_retry, done, failed, cancelled. For display only; branch on `status`.
    stage: str
    progress: int = Field(ge=0, le=100)
    attempts: int
    max_attempts: int
    cancel_requested: bool
    error_code: str | None
    # Safe to show a learner. Present on failed jobs, and on queued ones waiting for a retry.
    error_message: str | None
    # The roadmap this job produced, once a roadmap job has completed.
    roadmap_id: UUID | None
    # The lesson this job produced, once a lesson job has completed.
    lesson_id: UUID | None
    # The quiz this job produced, once a quiz job has completed.
    quiz_id: UUID | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class JobList(BaseModel):
    items: list[GenerationJob]
