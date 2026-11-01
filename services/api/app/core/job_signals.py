"""Which requests queued a job, so the worker can be woken once the request's transaction commits.

Code that inserts a ``generation_jobs`` row calls ``note_job_queued``. It does nothing outside a
request that is being watched (the worker, scripts, tests that do not opt in), and it never does
I/O itself: ``app.api.job_wake.JobWakeMiddleware`` reads the note when the response starts, which
is after the route's transaction has committed, and wakes the worker then.
"""

from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar

_queued: ContextVar[list[bool] | None] = ContextVar("jobs_queued", default=None)


def note_job_queued() -> None:
    """Record that the current request queued a job (a no-op outside a watched request)."""
    marks = _queued.get()
    if marks is not None:
        marks.append(True)


@contextmanager
def watch_job_signals() -> Generator[list[bool]]:
    """Collect ``note_job_queued`` calls made while the block runs (one entry per call)."""
    marks: list[bool] = []
    token = _queued.set(marks)
    try:
        yield marks
    finally:
        _queued.reset(token)
