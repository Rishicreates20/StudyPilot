"""How a job can end other than by finishing."""


class JobFailure(Exception):
    """A deliberate failure with a learner-safe message and a stable code.

    ``retryable`` says whether the worker should try again later (until the job's attempts run
    out) or stop now.
    """

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.message = message
        self.retryable = retryable


class JobCancelled(Exception):
    """The learner asked to cancel and the worker noticed at a stage boundary."""


class LeaseLost(Exception):
    """Another worker owns the job now (this one was too slow). Stop without writing anything."""
