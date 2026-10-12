"""Resting candidates: who is asked, who is left alone, and which error is shown at the end."""

import pytest

from app.ai.bench import (
    CONFIGURATION_REST_SECONDS,
    MAX_REST_SECONDS,
    REST_SECONDS,
    Bench,
    soonest,
)
from app.ai.provider import (
    LLMAuthError,
    LLMInvalidOutput,
    LLMQuotaExhausted,
    LLMRateLimited,
    LLMRejected,
    LLMUnavailable,
)

pytestmark = pytest.mark.anyio


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class Candidates:
    """A set of named candidates, each answering with a value or raising, and a call log."""

    def __init__(self, **outcomes: object) -> None:
        self.outcomes = outcomes
        self.calls: list[str] = []

    async def __call__(self, name: str) -> str:
        self.calls.append(name)
        outcome = self.outcomes[name]
        if isinstance(outcome, Exception):
            raise outcome
        return str(outcome)


def make_bench() -> tuple[Bench, Clock]:
    clock = Clock()
    return Bench("test", clock=clock), clock


async def test_the_first_candidate_that_can_answer_is_used() -> None:
    bench, _ = make_bench()
    candidates = Candidates(a="from a", b="from b")

    assert await bench.first_answer(["a", "b"], candidates) == ("from a", "a")
    assert candidates.calls == ["a"]


async def test_a_candidate_without_allowance_rests_and_the_next_one_answers() -> None:
    bench, _ = make_bench()
    candidates = Candidates(a=LLMQuotaExhausted("daily", retry_after=7200), b="from b")

    assert await bench.first_answer(["a", "b"], candidates) == ("from b", "b")

    # While it rests, a is not asked again: no request is spent finding out it is still spent.
    assert await bench.first_answer(["a", "b"], candidates) == ("from b", "b")
    assert candidates.calls == ["a", "b", "b"]


@pytest.mark.parametrize(
    "error",
    [LLMRateLimited("slow down"), LLMUnavailable("overloaded")],
)
async def test_a_busy_candidate_rests_for_the_default_time_when_it_does_not_say(
    error: Exception,
) -> None:
    bench, clock = make_bench()
    candidates = Candidates(a=error, b="from b")
    await bench.first_answer(["a", "b"], candidates)

    clock.now += REST_SECONDS - 1
    await bench.first_answer(["a", "b"], candidates)
    assert candidates.calls == ["a", "b", "b"]

    clock.now += 2  # the rest is over: a is asked again
    await bench.first_answer(["a", "b"], candidates)
    assert candidates.calls == ["a", "b", "b", "a", "b"]


async def test_a_candidate_rests_for_as_long_as_it_says_but_never_more_than_a_day() -> None:
    bench, _ = make_bench()
    error = LLMQuotaExhausted("daily", retry_after=10 * MAX_REST_SECONDS)
    seconds = bench.rest("a", error)

    assert seconds == MAX_REST_SECONDS
    resting = bench.resting("a")
    assert resting is not None and resting[0] == pytest.approx(MAX_REST_SECONDS)


async def test_a_candidate_set_up_wrongly_rests_for_an_hour_and_the_next_is_used() -> None:
    bench, clock = make_bench()
    candidates = Candidates(a=LLMAuthError("bad key"), b="from b")

    assert await bench.first_answer(["a", "b"], candidates) == ("from b", "b")

    clock.now += CONFIGURATION_REST_SECONDS - 1
    await bench.first_answer(["a", "b"], candidates)
    assert candidates.calls == ["a", "b", "b"]


async def test_when_nobody_can_answer_the_error_that_clears_first_is_raised() -> None:
    bench, _ = make_bench()
    candidates = Candidates(
        a=LLMQuotaExhausted("daily", retry_after=18000),
        b=LLMRateLimited("busy", retry_after=30),
        c=LLMUnavailable("down"),
    )

    with pytest.raises(LLMRateLimited) as raised:
        await bench.first_answer(["a", "b", "c"], candidates)

    assert raised.value.retry_after == 30


async def test_an_earlier_failure_counts_when_choosing_what_to_report() -> None:
    bench, _ = make_bench()
    candidates = Candidates(a=LLMQuotaExhausted("daily", retry_after=18000))
    earlier = [(120.0, LLMRateLimited("the primary is busy"))]

    with pytest.raises(LLMRateLimited) as raised:
        await bench.first_answer(["a"], candidates, earlier=earlier)

    assert raised.value.retry_after == 120


async def test_resting_candidates_still_count_towards_the_error() -> None:
    bench, clock = make_bench()
    candidates = Candidates(a=LLMQuotaExhausted("daily", retry_after=3600))
    with pytest.raises(LLMQuotaExhausted):
        await bench.first_answer(["a"], candidates)
    clock.now += 600

    with pytest.raises(LLMQuotaExhausted) as raised:
        await bench.first_answer(["a"], candidates)

    assert candidates.calls == ["a"]  # not asked again
    assert raised.value.retry_after == pytest.approx(3000)


async def test_a_busy_reason_is_reported_in_preference_to_a_configuration_problem() -> None:
    bench, _ = make_bench()
    candidates = Candidates(
        a=LLMAuthError("bad key"), b=LLMQuotaExhausted("daily", retry_after=18000)
    )

    with pytest.raises(LLMQuotaExhausted):
        await bench.first_answer(["a", "b"], candidates)


async def test_only_configuration_problems_are_reported_as_such() -> None:
    bench, _ = make_bench()
    candidates = Candidates(a=LLMAuthError("bad key"), b=LLMRejected("no such model"))

    with pytest.raises(LLMAuthError):
        await bench.first_answer(["a", "b"], candidates)

    # Next time both are resting, and the same reason is given without asking either.
    with pytest.raises(LLMAuthError):
        await bench.first_answer(["a", "b"], candidates)
    assert candidates.calls == ["a", "b"]


async def test_an_answer_that_was_wrong_is_the_callers_to_handle_and_does_not_rest_anyone() -> None:
    bench, _ = make_bench()
    candidates = Candidates(a=LLMInvalidOutput("not the schema"), b="from b")

    with pytest.raises(LLMInvalidOutput):
        await bench.first_answer(["a", "b"], candidates)

    assert bench.resting("a") is None
    assert candidates.calls == ["a"]


async def test_no_candidates_is_an_error_not_a_crash() -> None:
    bench, _ = make_bench()

    with pytest.raises(LLMUnavailable):
        await bench.first_answer([], Candidates())


def test_soonest_keeps_the_kind_of_error_and_states_the_wait() -> None:
    error = soonest(
        [
            (500.0, LLMUnavailable("later")),
            (45.0, LLMQuotaExhausted("sooner", retry_after=99999)),
        ]
    )

    assert isinstance(error, LLMQuotaExhausted)
    assert error.retry_after == 45
    assert error.detail == "sooner"
