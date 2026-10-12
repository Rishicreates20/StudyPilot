"""Resting candidates: who is asked, who is left alone, and which error is shown at the end."""

import pytest

from app.ai.bench import (
    CONFIGURATION_REST_SECONDS,
    MAX_REST_SECONDS,
    REST_SECONDS,
    Bench,
    rest_for,
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

    def __init__(self, clock: Clock | None = None, **outcomes: object) -> None:
        self.outcomes = outcomes
        self.calls: list[str] = []
        self._clock = clock
        # Seconds a candidate takes to answer (the clock moves while it is being asked).
        self.takes: dict[str, float] = {}

    async def __call__(self, name: str) -> str:
        self.calls.append(name)
        if self._clock is not None:
            self._clock.now += self.takes.get(name, 0.0)
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
    bench, clock = make_bench()
    error = LLMQuotaExhausted("daily", retry_after=10 * MAX_REST_SECONDS)

    clears_at = bench.rest("a", error)

    assert clears_at == clock.now + MAX_REST_SECONDS
    resting = bench.resting("a")
    assert resting is not None and resting[0] == pytest.approx(MAX_REST_SECONDS)


async def test_a_provider_that_says_retry_now_is_not_made_to_wait() -> None:
    bench, _ = make_bench()
    candidates = Candidates(a=LLMRateLimited("busy", retry_after=0), b="from b")

    await bench.first_answer(["a", "b"], candidates)
    await bench.first_answer(["a", "b"], candidates)

    assert rest_for(LLMRateLimited("busy", retry_after=0)) == 0
    assert bench.resting("a") is None
    assert candidates.calls == ["a", "b", "a", "b"]  # asked again at once, as it said


async def test_a_candidate_whose_credentials_are_refused_rests_for_an_hour() -> None:
    bench, clock = make_bench()
    candidates = Candidates(a=LLMAuthError("bad key"), b="from b")

    assert await bench.first_answer(["a", "b"], candidates) == ("from b", "b")

    clock.now += CONFIGURATION_REST_SECONDS - 1
    await bench.first_answer(["a", "b"], candidates)
    assert candidates.calls == ["a", "b", "b"]


# --- A refused request is not a resting candidate --------------------------------------------


async def test_a_refused_request_passes_to_the_next_candidate_and_rests_nobody() -> None:
    bench, _ = make_bench()
    candidates = Candidates(a=LLMRejected("prompt too long for this model"), b="from b")

    assert await bench.first_answer(["a", "b"], candidates) == ("from b", "b")
    # The next request may suit a perfectly well: it is asked first again.
    assert await bench.first_answer(["a", "b"], candidates) == ("from b", "b")

    assert bench.resting("a") is None
    assert candidates.calls == ["a", "b", "a", "b"]


async def test_a_request_every_candidate_refuses_is_reported_as_refused() -> None:
    bench, _ = make_bench()
    candidates = Candidates(a=LLMRejected("first refusal"), b=LLMRejected("second refusal"))

    with pytest.raises(LLMRejected) as raised:
        await bench.first_answer(["a", "b"], candidates)

    assert raised.value.detail == "first refusal"
    assert bench.resting("a") is None and bench.resting("b") is None


async def test_a_busy_reason_is_reported_in_preference_to_a_refusal() -> None:
    bench, _ = make_bench()
    candidates = Candidates(a=LLMRejected("refused"), b=LLMRateLimited("busy", retry_after=30))

    with pytest.raises(LLMRateLimited):
        await bench.first_answer(["a", "b"], candidates)


# --- Which error is shown when nobody can answer ---------------------------------------------


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


async def test_the_wait_reported_is_what_is_left_now_not_what_it_was_when_it_began() -> None:
    bench, clock = make_bench()
    candidates = Candidates(
        clock,
        a=LLMRateLimited("busy", retry_after=40),
        b=LLMQuotaExhausted("daily", retry_after=600),
    )
    candidates.takes["b"] = 30  # b is slow: 30 seconds pass before it fails

    with pytest.raises(LLMRateLimited) as raised:
        await bench.first_answer(["a", "b"], candidates)

    # a said 40 s at the start; 30 s have gone by, so 10 s are left, not 40.
    assert raised.value.retry_after == pytest.approx(10)


async def test_a_candidate_that_has_already_cleared_is_reported_with_no_wait() -> None:
    bench, clock = make_bench()
    candidates = Candidates(
        clock,
        a=LLMRateLimited("busy", retry_after=5),
        b=LLMQuotaExhausted("daily", retry_after=600),
    )
    candidates.takes["b"] = 30

    with pytest.raises(LLMRateLimited) as raised:
        await bench.first_answer(["a", "b"], candidates)

    assert raised.value.retry_after == 0


async def test_an_earlier_failure_counts_when_choosing_what_to_report() -> None:
    bench, clock = make_bench()
    candidates = Candidates(a=LLMQuotaExhausted("daily", retry_after=18000))
    earlier = [(clock.now + 120, LLMRateLimited("the primary is busy"))]

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


async def test_an_allowance_that_never_said_when_it_resets_is_not_given_a_made_up_wait() -> None:
    bench, _ = make_bench()
    candidates = Candidates(a=LLMQuotaExhausted("daily"), b=LLMQuotaExhausted("daily"))

    with pytest.raises(LLMQuotaExhausted) as raised:
        await bench.first_answer(["a", "b"], candidates)

    # Our one-minute guess for how long to rest must not become "resets in about 1 hour".
    assert raised.value.retry_after is None
    assert "resets in" not in raised.value.user_message


async def test_a_credentials_problem_is_only_reported_when_it_is_all_there_is() -> None:
    bench, _ = make_bench()
    candidates = Candidates(
        a=LLMAuthError("bad key"), b=LLMQuotaExhausted("daily", retry_after=18000)
    )

    with pytest.raises(LLMQuotaExhausted):
        await bench.first_answer(["a", "b"], candidates)


async def test_only_credentials_problems_are_reported_as_such() -> None:
    bench, _ = make_bench()
    candidates = Candidates(a=LLMAuthError("bad key"), b=LLMAuthError("also bad"))

    with pytest.raises(LLMAuthError) as raised:
        await bench.first_answer(["a", "b"], candidates)

    assert raised.value.detail == "bad key"
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


def test_soonest_keeps_the_kind_of_error_and_states_the_wait_left() -> None:
    error = soonest(
        [
            (1500.0, LLMUnavailable("later")),
            (1045.0, LLMQuotaExhausted("sooner", retry_after=99999)),
        ],
        now=1000.0,
    )

    assert isinstance(error, LLMQuotaExhausted)
    assert error.retry_after == 45
    assert error.detail == "sooner"
