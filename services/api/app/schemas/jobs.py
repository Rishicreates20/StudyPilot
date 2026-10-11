"""Background jobs as the API shows them: learner-safe status, never prompts or model output."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

JobStatus = Literal["queued", "running", "completed", "failed", "cancelled"]
JobType = Literal["roadmap", "lesson"]


class GenerationJob(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    goal_id: UUID
    job_type: JobType
    # The roadmap topic a lesson job is writing for; None for roadmap jobs.
    item_id: UUID | None
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
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class JobList(BaseModel):
    items: list[GenerationJob]
