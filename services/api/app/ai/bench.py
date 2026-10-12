"""Candidates that cannot answer right now are left alone for a while, and the next one is asked.

A free tier gives every model (and every provider) its own small allowance, so running out is
normal, not an incident. ``Bench`` remembers who is resting and until when, so a job does not spend
a request (or a learner's patience) rediscovering that a model is spent. The OpenAI-compatible
adapter uses it over its models, the provider chain over its providers.
"""

import time
from collections.abc import Awaitable, Callable, Sequence

import structlog

from app.ai.provider import (
    LLMAuthError,
    LLMError,
    LLMQuotaExhausted,
    LLMRateLimited,
    LLMRejected,
    LLMTimeout,
    LLMUnavailable,
)

log = structlog.get_logger("app.ai.bench")

# How long a candidate rests when its provider does not say, and at most.
REST_SECONDS = 60.0
MAX_REST_SECONDS = 24 * 3600.0
# A rejected key or a model the key may not use will not fix itself in a minute.
CONFIGURATION_REST_SECONDS = 3600.0

# Failures that mean "not now": the next candidate may well answer.
BUSY = (LLMQuotaExhausted, LLMRateLimited, LLMUnavailable, LLMTimeout)
# Failures that mean "this candidate is set up wrongly": it rests for longer and nobody is told
# the provider's reason, only that another candidate was used.
MISCONFIGURED = (LLMAuthError, LLMRejected)


def soonest(errors: Sequence[tuple[float, LLMError]]) -> LLMError:
    """The most useful error to show when nobody could answer: the one that clears first.

    A daily-allowance error carries how long until it resets, a busy error how long to wait.
    """
    wait, error = min(errors, key=lambda item: item[0])
    return type(error)(error.detail, retry_after=wait)


def rest_for(error: LLMError) -> float:
    """How long to leave a candidate alone after ``error``."""
    if isinstance(error, MISCONFIGURED):
        return CONFIGURATION_REST_SECONDS
    return min(error.retry_after or REST_SECONDS, MAX_REST_SECONDS)


class Bench:
    def __init__(self, label: str, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._label = label
        self._clock = clock
        # name -> (the time it may be tried again, the error that benched it)
        self._resting: dict[str, tuple[float, LLMError]] = {}

    def resting(self, name: str) -> tuple[float, LLMError] | None:
        """``(seconds left, the error)`` if ``name`` is resting now."""
        entry = self._resting.get(name)
        if entry is None:
            return None
        left = entry[0] - self._clock()
        return (left, entry[1]) if left > 0 else None

    def rest(self, name: str, error: LLMError) -> float:
        seconds = rest_for(error)
        self._resting[name] = (self._clock() + seconds, error)
        log.warning(
            "ai.candidate_resting",
            group=self._label,
            candidate=name,
            code=error.code,
            seconds=round(seconds),
        )
        return seconds

    async def first_answer[T](
        self,
        names: Sequence[str],
        attempt: Callable[[str], Awaitable[T]],
        *,
        earlier: Sequence[tuple[float, LLMError]] = (),
    ) -> tuple[T, str]:
        """The result of the first candidate that can answer, and its name.

        A candidate that is out of allowance, rate limited, overloaded, or set up wrongly rests and
        the next is tried. Any other error is the caller's to handle and passes through. When
        nobody can answer, ``soonest`` of the busy reasons (``earlier`` ones included) is raised;
        if the only reasons are configuration problems, the first of them is.
        """
        busy: list[tuple[float, LLMError]] = list(earlier)
        misconfigured: list[LLMError] = []
        for name in names:
            resting = self.resting(name)
            if resting is not None:
                left, error = resting
                if isinstance(error, MISCONFIGURED):
                    misconfigured.append(error)
                else:
                    busy.append((left, error))
                continue
            try:
                return await attempt(name), name
            except BUSY as exc:
                busy.append((self.rest(name, exc), exc))
            except MISCONFIGURED as exc:
                self.rest(name, exc)
                misconfigured.append(exc)
        if busy:
            raise soonest(busy)
        if misconfigured:
            raise misconfigured[0]
        raise LLMUnavailable("no candidate was available")
