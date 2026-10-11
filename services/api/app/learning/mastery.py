"""How well a learner knows a topic: a transparent score computed from the answers they gave.

This is deliberately simple, deterministic and explainable (ADR-010, ADR-036). No model is involved
and nothing here reads the database: the caller hands in the graded answers, so the same answers
always give the same score and the method can be replaced later (a new ``ALGORITHM_VERSION``) and
every topic recomputed from the stored answers.

The method
----------
Every answered question carries a weight and an earned fraction:

* its **difficulty weight** is what the question was worth (easy 1, medium 2, hard 3), so a hard
  question counts for more than an easy one;
* its **recency weight** is ``decay ** rank`` where ``rank`` is 0 for the newest attempt, 1 for the
  one before it and so on, so a topic you have since improved at is not held back by an old quiz;
* its **earned fraction** is the points awarded divided by the points it was worth (a skipped
  question earns 0; a short answer may earn part of its points).

``score = 100 * sum(weight * earned_fraction) / sum(weight)``, where ``weight`` is the product of
the two weights. The same formula over only the answers that test one objective gives that
objective's score, which is how a weak *part* of a topic is found. The score is put into a band by
two thresholds from configuration: below ``needs_practice_below`` the topic needs practice, from
``mastered_from`` it counts as mastered, in between it is progressing. With fewer than
``min_answers`` answers the score is marked as an early estimate (``low_confidence``).
"""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from app.core.config import Settings

ALGORITHM_VERSION = "weighted-recency/v1"

Band = Literal["needs_practice", "progressing", "mastered"]


@dataclass(frozen=True)
class MasteryConfig:
    needs_practice_below: float = 70.0
    mastered_from: float = 90.0
    recency_decay: float = 0.7
    min_answers: int = 4

    @classmethod
    def from_settings(cls, settings: Settings) -> MasteryConfig:
        return cls(
            needs_practice_below=settings.mastery_needs_practice_below,
            mastered_from=settings.mastery_mastered_from,
            recency_decay=settings.mastery_recency_decay,
            min_answers=settings.mastery_min_answers,
        )

    def __post_init__(self) -> None:
        if not 0 < self.needs_practice_below < self.mastered_from <= 100:
            raise ValueError(
                "needs_practice_below must be above 0 and below mastered_from (<= 100)"
            )
        if not 0 < self.recency_decay <= 1:
            raise ValueError("recency_decay must be in (0, 1]")
        if self.min_answers < 1:
            raise ValueError("min_answers must be at least 1")


@dataclass(frozen=True)
class AnsweredQuestion:
    """One graded answer, as the scoring method sees it."""

    # 0 for the newest graded attempt of the topic, 1 for the one before, and so on.
    attempt_rank: int
    objective_id: str
    # What the question was worth: 1 easy, 2 medium, 3 hard.
    possible: int
    earned: float


@dataclass(frozen=True)
class ObjectiveScore:
    id: str
    score: float
    answers: int


@dataclass(frozen=True)
class MasteryResult:
    score: float
    band: Band
    attempts: int
    answers: int
    low_confidence: bool
    objectives: tuple[ObjectiveScore, ...]

    def weak_objectives(self, config: MasteryConfig) -> tuple[str, ...]:
        """Objectives scoring below the needs-practice threshold, weakest first."""
        weak = [o for o in self.objectives if o.score < config.needs_practice_below]
        return tuple(o.id for o in sorted(weak, key=lambda o: (o.score, o.id)))


def band_for_thresholds(score: float, needs_practice_below: float, mastered_from: float) -> Band:
    """The band a score falls in. The band is derived from the score each time it is shown, so a
    changed threshold applies to every stored result at once (nothing is re-graded)."""
    if score < needs_practice_below:
        return "needs_practice"
    if score >= mastered_from:
        return "mastered"
    return "progressing"


def band_for(score: float, config: MasteryConfig) -> Band:
    return band_for_thresholds(score, config.needs_practice_below, config.mastered_from)


def _weighted_percent(answers: Sequence[AnsweredQuestion], decay: float) -> float:
    total = 0.0
    earned = 0.0
    for answer in answers:
        weight = answer.possible * decay**answer.attempt_rank
        total += weight
        earned += weight * min(1.0, max(0.0, answer.earned / answer.possible))
    return 100.0 * earned / total


def compute_mastery(
    answers: Sequence[AnsweredQuestion], config: MasteryConfig
) -> MasteryResult | None:
    """The mastery of one topic from its graded answers, or None if there are none."""
    if not answers:
        return None
    score = round(_weighted_percent(answers, config.recency_decay), 2)

    by_objective: dict[str, list[AnsweredQuestion]] = defaultdict(list)
    for answer in answers:
        by_objective[answer.objective_id].append(answer)
    objectives = tuple(
        ObjectiveScore(
            id=objective_id,
            score=round(_weighted_percent(group, config.recency_decay), 2),
            answers=len(group),
        )
        for objective_id, group in sorted(by_objective.items())
    )
    return MasteryResult(
        score=score,
        band=band_for(score, config),
        attempts=len({answer.attempt_rank for answer in answers}),
        answers=len(answers),
        low_confidence=len(answers) < config.min_answers,
        objectives=objectives,
    )
