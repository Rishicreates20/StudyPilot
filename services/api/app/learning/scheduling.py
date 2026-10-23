"""When a flashcard is next due: a small, deterministic, SM-2-style schedule (ADR-050).

Nothing here reads the database or the clock: the caller hands in the card's current schedule, the
learner's rating and the time, so the same inputs always give the same result. The method can be
replaced later (a new ``SCHEDULER_VERSION``): every review stores the schedule before and after
and the version that made it, so old history can be replayed.

This is a well-known *heuristic*, not something validated for any particular learner or subject.
It is described to learners as a suggestion for when to look at a card again.

The method
----------
The learner answers one of four ratings. ``again`` means they did not remember; the card comes back
in ``RELEARN_MINUTES`` and its run of successes starts over. The other three schedule the next
review in whole days:

* a card seen for the first time: ``good`` is 1 day, ``easy`` is 4 days, ``hard`` is 1 day;
* the second success: ``good`` is 6 days (the classic SM-2 step);
* after that ``good`` multiplies the last interval by the card's **ease factor**, ``easy`` goes
  30% further than ``good``, and ``hard`` grows it only by 20%;
* every interval is at least one day longer than the last for ``good`` and ``easy`` and never longer
  than ``MAX_INTERVAL_DAYS``.

The ease factor starts at 2.50 and moves with the ratings (``again`` -0.20, ``hard`` -0.15, ``easy``
+0.15, ``good`` unchanged) within 1.30 to 3.50, so a card that keeps being forgotten is shown more
often than one that never is.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

SCHEDULER_VERSION = "sm2-v1"

Rating = Literal["again", "hard", "good", "easy"]
RATINGS: tuple[Rating, ...] = ("again", "hard", "good", "easy")

START_EASE = 2.50
MIN_EASE = 1.30
MAX_EASE = 3.50
MAX_INTERVAL_DAYS = 365
RELEARN_MINUTES = 10

_EASE_CHANGE: dict[Rating, float] = {"again": -0.20, "hard": -0.15, "good": 0.0, "easy": 0.15}
_FIRST_GOOD_DAYS = 1
_SECOND_GOOD_DAYS = 6
_FIRST_EASY_DAYS = 4
_HARD_GROWTH = 1.2
_EASY_BONUS = 1.3


@dataclass(frozen=True)
class CardSchedule:
    """The part of a card the schedule reads and writes."""

    interval_days: int
    ease_factor: float
    repetitions: int
    lapses: int


@dataclass(frozen=True)
class Scheduled:
    """A card's schedule after a review, and when to show it next."""

    interval_days: int
    ease_factor: float
    repetitions: int
    lapses: int
    due_at: datetime


NEW_CARD = CardSchedule(interval_days=0, ease_factor=START_EASE, repetitions=0, lapses=0)


def _clamp_ease(value: float) -> float:
    return round(min(MAX_EASE, max(MIN_EASE, value)), 2)


def _round_half_up(value: float) -> int:
    """Whole days, with a half rounded up (Python's ``round`` would send 32.5 to 32)."""
    return int(value + 0.5)


def _good_days(schedule: CardSchedule) -> int:
    if schedule.repetitions == 0:
        return _FIRST_GOOD_DAYS
    if schedule.repetitions == 1:
        return _SECOND_GOOD_DAYS
    return max(
        schedule.interval_days + 1,
        _round_half_up(schedule.interval_days * schedule.ease_factor),
    )


def _days_for(schedule: CardSchedule, rating: Rating) -> int:
    good = _good_days(schedule)
    if rating == "good":
        days = good
    elif rating == "easy":
        if schedule.repetitions == 0:
            days = _FIRST_EASY_DAYS
        else:
            days = max(good + 1, _round_half_up(good * _EASY_BONUS))
    else:  # hard: grows the interval a little, never beyond what "good" would give
        days = max(1, min(good, _round_half_up(max(schedule.interval_days, 1) * _HARD_GROWTH)))
    return min(MAX_INTERVAL_DAYS, days)


def schedule_review(schedule: CardSchedule, rating: Rating, now: datetime) -> Scheduled:
    """The card's new schedule after ``rating`` at ``now`` (a timezone-aware time)."""
    ease = _clamp_ease(schedule.ease_factor + _EASE_CHANGE[rating])
    if rating == "again":
        return Scheduled(
            interval_days=0,
            ease_factor=ease,
            repetitions=0,
            lapses=schedule.lapses + 1,
            due_at=now + timedelta(minutes=RELEARN_MINUTES),
        )
    days = _days_for(schedule, rating)
    return Scheduled(
        interval_days=days,
        ease_factor=ease,
        repetitions=schedule.repetitions + 1,
        lapses=schedule.lapses,
        due_at=now + timedelta(days=days),
    )
