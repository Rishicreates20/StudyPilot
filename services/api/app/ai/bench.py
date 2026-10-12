"""Candidates that cannot answer right now are left alone for a while, and the next one is asked.

A free tier gives every model (and every provider) its own small allowance, so running out is
normal, not an incident. ``Bench`` remembers who is resting and until when, so a job does not spend
a request (or a learner's patience) rediscovering that a model is spent. The OpenAI-compatible
adapter uses it over its models, the provider chain over its providers.

Three kinds of failure are told apart, because they call for different things:

* *busy* (out of allowance, rate limited, overloaded, timed out): the candidate rests for the time
  it says (a minute when it does not) and the next one is asked;
* *misconfigured* (a rejected key): resting for an hour, then the next is asked;
* *refused* (the provider turned down this request: a prompt too long for that model, an unknown
  model id): the next is asked but nobody rests, because it is this request that was refused, not
  the candidate that is out of action, and one odd request must not sideline anyone for an hour.

Two callers that arrive together may both try a candidate that has only just run out; the loser
spends one request on a refusal. Preventing that would mean holding every caller back for the length
of a model call, which costs far more than it saves, so it is accepted.
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
# A rejected key will not fix itself in a minute.
CONFIGURATION_REST_SECONDS = 3600.0

# Failures that mean "not now": the next candidate may well answer.
BUSY = (LLMQuotaExhausted, LLMRateLimited, LLMUnavailable, LLMTimeout)
# A candidate whose credentials are refused: it rests for longer.
MISCONFIGURED = (LLMAuthError,)
# This request was refused (not the candidate's fault, and not worth resting it for).
REFUSED = (LLMRejected,)


def rest_for(error: LLMError) -> float:
    """How long to leave a candidate alone after ``error`` (0 when the provider says retry now)."""
    if isinstance(error, MISCONFIGURED):
        return CONFIGURATION_REST_SECONDS
    seconds = REST_SECONDS if error.retry_after is None else error.retry_after
    return max(0.0, min(seconds, MAX_REST_SECONDS))


def soonest(errors: Sequence[tuple[float, LLMError]], *, now: float) -> LLMError:
    """The most useful error to show when nobody could answer: the one that clears first.

    Each entry is ``(the time it clears, the error)``. The wait stated is what is left *now*, not
    what it was when the failure happened (a slow candidate tried later may have used it up). An
    allowance error whose provider never said when it resets is stated without a wait: showing
    our own one-minute guess as "resets in about 1 hour" would be wrong.
    """
    clears_at, error = min(errors, key=lambda item: item[0])
    unknown_reset = isinstance(error, LLMQuotaExhausted) and error.retry_after is None
    return type(error)(
        error.detail, retry_after=None if unknown_reset else max(clears_at - now, 0.0)
    )


class Bench:
    def __init__(self, label: str, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._label = label
        self._clock = clock
        # name -> (the time it may be tried again, the error that benched it)
        self._resting: dict[str, tuple[float, LLMError]] = {}

    def now(self) -> float:
        return self._clock()

    def resting(self, name: str) -> tuple[float, LLMError] | None:
        """``(seconds left, the error)`` if ``name`` is resting now."""
        entry = self._resting.get(name)
        if entry is None:
            return None
        left = entry[0] - self._clock()
        return (left, entry[1]) if left > 0 else None

    def rest(self, name: str, error: LLMError) -> float:
        """Leave ``name`` alone after ``error``; the time (on this bench's clock) it clears."""
        seconds = rest_for(error)
        clears_at = self._clock() + seconds
        self._resting[name] = (clears_at, error)
        log.warning(
            "ai.candidate_resting",
            group=self._label,
            candidate=name,
            code=error.code,
            seconds=round(seconds),
        )
        return clears_at

    async def first_answer[T](
        self,
        names: Sequence[str],
        attempt: Callable[[str], Awaitable[T]],
        *,
        earlier: Sequence[tuple[float, LLMError]] = (),
    ) -> tuple[T, str]:
        """The result of the first candidate that can answer, and its name.

        A busy or misconfigured candidate rests and the next is tried; a candidate that refuses the
        request is passed over without resting. Any other error is the caller's to handle and
        passes through. When nobody can answer, ``soonest`` of the busy reasons (``earlier`` ones,
        as ``(time it clears, error)``, included) is raised; failing those, a credentials
        problem; failing that, the first refusal.
        """
        busy: list[tuple[float, LLMError]] = list(earlier)
        misconfigured: list[LLMError] = []
        refused: list[LLMError] = []
        for name in names:
            entry = self._resting.get(name)
            if entry is not None and entry[0] > self._clock():
                if isinstance(entry[1], MISCONFIGURED):
                    misconfigured.append(entry[1])
                else:
                    busy.append(entry)
                continue
            try:
                return await attempt(name), name
            except BUSY as exc:
                busy.append((self.rest(name, exc), exc))
            except MISCONFIGURED as exc:
                self.rest(name, exc)
                misconfigured.append(exc)
            except REFUSED as exc:
                refused.append(exc)
        if busy:
            raise soonest(busy, now=self._clock())
        if misconfigured:
            raise misconfigured[0]
        if refused:
            raise refused[0]
        raise LLMUnavailable("no candidate was available")
