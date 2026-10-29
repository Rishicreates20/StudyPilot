"""The flashcard schedule: pure functions, so behaviour is checkable without a database."""

from datetime import UTC, datetime, timedelta

import pytest

from app.learning.scheduling import (
    MAX_EASE,
    MAX_INTERVAL_DAYS,
    MIN_EASE,
    NEW_CARD,
    RATINGS,
    RELEARN_MINUTES,
    SCHEDULER_VERSION,
    START_EASE,
    CardSchedule,
    Rating,
    schedule_review,
)

NOW = datetime(2026, 10, 23, 9, 0, tzinfo=UTC)


def review(schedule: CardSchedule, rating: Rating) -> CardSchedule:
    result = schedule_review(schedule, rating, NOW)
    return CardSchedule(result.interval_days, result.ease_factor, result.repetitions, result.lapses)


def test_the_version_is_recorded_with_every_review() -> None:
    assert SCHEDULER_VERSION == "sm2-v1"


# --- A card seen for the first time ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("rating", "days"), [("hard", 1), ("good", 1), ("easy", 4)], ids=lambda value: str(value)
)
def test_the_first_review_of_a_new_card_schedules_it_in_whole_days(
    rating: Rating, days: int
) -> None:
    result = schedule_review(NEW_CARD, rating, NOW)

    assert result.interval_days == days
    assert result.due_at == NOW + timedelta(days=days)
    assert result.repetitions == 1
    assert result.lapses == 0


def test_forgetting_a_new_card_brings_it_back_in_minutes_and_counts_a_lapse() -> None:
    result = schedule_review(NEW_CARD, "again", NOW)

    assert result.interval_days == 0
    assert result.due_at == NOW + timedelta(minutes=RELEARN_MINUTES)
    assert result.repetitions == 0
    assert result.lapses == 1
    assert result.ease_factor == pytest.approx(START_EASE - 0.20)


# --- Growth ---------------------------------------------------------------------------------------


def test_repeated_good_answers_follow_the_classic_steps_and_then_multiply_by_ease() -> None:
    card = NEW_CARD
    intervals: list[int] = []
    for _ in range(5):
        card = review(card, "good")
        intervals.append(card.interval_days)

    assert intervals[:2] == [1, 6]
    assert intervals[2] == round(6 * START_EASE)  # 15
    assert intervals[3] == round(15 * START_EASE)  # 38
    assert intervals == sorted(set(intervals)), "each good review pushes the next one further out"
    assert card.ease_factor == START_EASE  # good leaves the ease alone


def test_forgetting_a_mature_card_resets_its_run_and_lowers_its_ease() -> None:
    mature = CardSchedule(interval_days=40, ease_factor=2.5, repetitions=6, lapses=1)

    result = schedule_review(mature, "again", NOW)

    assert (result.interval_days, result.repetitions, result.lapses) == (0, 0, 2)
    assert result.ease_factor == pytest.approx(2.30)
    # Coming back after a lapse starts the steps again.
    assert review(review(CardSchedule(0, 2.3, 0, 2), "good"), "good").interval_days == 6


def test_hard_grows_the_interval_a_little_and_easy_goes_further_than_good() -> None:
    mature = CardSchedule(interval_days=10, ease_factor=2.5, repetitions=4, lapses=0)

    hard = schedule_review(mature, "hard", NOW)
    good = schedule_review(mature, "good", NOW)
    easy = schedule_review(mature, "easy", NOW)

    assert hard.interval_days == 12  # 10 * 1.2
    assert good.interval_days == 25  # 10 * 2.5
    assert easy.interval_days == 33  # 25 * 1.3 rounded
    assert hard.ease_factor == pytest.approx(2.35)
    assert easy.ease_factor == pytest.approx(2.65)


# --- Bounds ---------------------------------------------------------------------------------------


def test_the_interval_never_exceeds_the_cap() -> None:
    old = CardSchedule(interval_days=300, ease_factor=3.5, repetitions=12, lapses=0)

    for rating in ("hard", "good", "easy"):
        assert schedule_review(old, rating, NOW).interval_days <= MAX_INTERVAL_DAYS
    assert schedule_review(old, "easy", NOW).interval_days == MAX_INTERVAL_DAYS


def test_the_ease_factor_stays_within_its_bounds() -> None:
    low = CardSchedule(interval_days=0, ease_factor=MIN_EASE, repetitions=0, lapses=9)
    high = CardSchedule(interval_days=20, ease_factor=MAX_EASE, repetitions=5, lapses=0)

    assert schedule_review(low, "again", NOW).ease_factor == MIN_EASE
    assert schedule_review(low, "hard", NOW).ease_factor == MIN_EASE
    assert schedule_review(high, "easy", NOW).ease_factor == MAX_EASE


def test_a_card_that_keeps_being_forgotten_ends_up_at_the_lowest_ease() -> None:
    card = NEW_CARD
    for _ in range(20):
        card = review(card, "again")

    assert card.ease_factor == MIN_EASE
    assert card.lapses == 20


# --- Properties that must hold for every state ---------------------------------------------------


def _reachable_states(depth: int) -> list[CardSchedule]:
    """Every schedule a card can be in after up to ``depth`` reviews, starting from a new card."""
    seen = {NEW_CARD}
    frontier = [NEW_CARD]
    for _ in range(depth):
        following: list[CardSchedule] = []
        for state in frontier:
            for rating in RATINGS:
                result = review(state, rating)
                if result not in seen:
                    seen.add(result)
                    following.append(result)
        frontier = following
    return sorted(seen, key=lambda s: (s.repetitions, s.interval_days, s.ease_factor, s.lapses))


# Real cards only: found by applying every sequence of ratings, not by guessing combinations.
STATES = _reachable_states(8)


def test_the_sweep_covers_the_extremes_a_real_card_reaches() -> None:
    assert len(STATES) > 100
    assert any(s.interval_days == MAX_INTERVAL_DAYS for s in STATES)
    assert any(s.ease_factor == MIN_EASE for s in STATES)
    assert any(s.ease_factor == MAX_EASE for s in STATES)
    assert any(s.lapses >= 3 for s in STATES)


@pytest.mark.parametrize("rating", RATINGS)
def test_every_result_is_inside_the_bounds_the_database_enforces(rating: Rating) -> None:
    for state in STATES:
        result = schedule_review(state, rating, NOW)

        assert 0 <= result.interval_days <= MAX_INTERVAL_DAYS
        assert MIN_EASE <= result.ease_factor <= MAX_EASE
        assert result.repetitions >= 0 and result.lapses >= 0
        assert result.due_at > NOW
        assert round(result.ease_factor, 2) == result.ease_factor, "fits numeric(3, 2)"


def test_the_ratings_are_ordered_from_hardest_to_easiest_for_every_state() -> None:
    for state in STATES:
        again, hard, good, easy = (schedule_review(state, r, NOW) for r in RATINGS)

        assert again.due_at < hard.due_at <= good.due_at <= easy.due_at
        assert again.interval_days == 0
        assert hard.interval_days <= good.interval_days <= easy.interval_days
        assert good.interval_days > state.interval_days or good.interval_days == MAX_INTERVAL_DAYS


def test_the_same_inputs_always_give_the_same_result() -> None:
    for state in STATES[:40]:
        for rating in RATINGS:
            assert schedule_review(state, rating, NOW) == schedule_review(state, rating, NOW)


def test_a_review_does_not_change_the_card_it_was_given() -> None:
    card = CardSchedule(interval_days=6, ease_factor=2.5, repetitions=2, lapses=0)

    schedule_review(card, "again", NOW)

    assert card == CardSchedule(interval_days=6, ease_factor=2.5, repetitions=2, lapses=0)
