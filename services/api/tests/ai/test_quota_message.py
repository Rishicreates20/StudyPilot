"""What a learner is told when a daily allowance is used up."""

import pytest

from app.ai.provider import LLMQuotaExhausted


@pytest.mark.parametrize(
    ("seconds", "said"),
    [
        (30, "about 1 minute."),
        (60, "about 1 minute."),
        (120, "about 2 minutes."),
        (45 * 60, "about 45 minutes."),
        (3600, "about 1 hour."),
        (5 * 3600, "about 5 hours."),
        (19 * 3600, "about 19 hours."),
    ],
)
def test_a_wait_is_said_in_the_unit_that_fits_it(seconds: float, said: str) -> None:
    assert said in LLMQuotaExhausted("daily", retry_after=seconds).user_message


@pytest.mark.parametrize("retry_after", [None, 0])
def test_without_a_wait_the_message_makes_no_promise_about_when(retry_after: float | None) -> None:
    message = LLMQuotaExhausted("daily", retry_after=retry_after).user_message

    assert "resets in" not in message and "tomorrow" in message
