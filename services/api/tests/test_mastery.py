"""Mastery and the next step: pure functions, so the behaviour is checkable without a database."""

from uuid import uuid4

import pytest

from app.learning.mastery import (
    ALGORITHM_VERSION,
    AnsweredQuestion,
    MasteryConfig,
    MasteryResult,
    ObjectiveScore,
    band_for,
    band_for_thresholds,
    compute_mastery,
)
from app.learning.recommend import Recommendation, TopicState, recommend
from support.settings import valid_local_settings

CONFIG = MasteryConfig(needs_practice_below=70, mastered_from=90, recency_decay=0.7, min_answers=4)


def answer(
    earned: float, possible: int = 1, *, rank: int = 0, objective: str = "o1"
) -> AnsweredQuestion:
    return AnsweredQuestion(
        attempt_rank=rank, objective_id=objective, possible=possible, earned=earned
    )


# --- Scoring ----------------------------------------------------------------------------------


def test_no_answers_means_no_mastery() -> None:
    assert compute_mastery([], CONFIG) is None


def test_the_score_is_the_share_of_points_earned() -> None:
    result = compute_mastery([answer(1), answer(1), answer(0), answer(1)], CONFIG)

    assert result is not None
    assert result.score == 75.0
    assert result.answers == 4 and result.attempts == 1


def test_a_hard_question_counts_for_more_than_an_easy_one() -> None:
    hard_right = compute_mastery([answer(3, 3), answer(0, 1)], CONFIG)
    easy_right = compute_mastery([answer(0, 3), answer(1, 1)], CONFIG)

    assert hard_right is not None and easy_right is not None
    assert hard_right.score == 75.0  # 3 of the 4 weighted points
    assert easy_right.score == 25.0


def test_part_credit_on_a_short_answer_counts_proportionally() -> None:
    result = compute_mastery([answer(1.5, 3)], CONFIG)

    assert result is not None and result.score == 50.0


def test_a_newer_attempt_counts_more_than_an_older_one() -> None:
    improved = compute_mastery([answer(0, rank=1), answer(1, rank=0)], CONFIG)
    declined = compute_mastery([answer(1, rank=1), answer(0, rank=0)], CONFIG)

    assert improved is not None and declined is not None
    assert improved.score > 50 > declined.score
    # newest weight 1, older 0.7: 1 / 1.7 of the points
    assert improved.score == pytest.approx(58.82, abs=0.01)
    assert improved.attempts == 2


def test_with_no_decay_every_attempt_counts_equally() -> None:
    flat = MasteryConfig(recency_decay=1.0)

    result = compute_mastery([answer(0, rank=3), answer(1, rank=0)], flat)

    assert result is not None and result.score == 50.0


def test_the_result_does_not_depend_on_the_order_the_answers_arrive_in() -> None:
    answers = [answer(1, 2, rank=0), answer(0, 1, rank=1), answer(1, 3, rank=0, objective="o2")]

    forward = compute_mastery(answers, CONFIG)
    backward = compute_mastery(list(reversed(answers)), CONFIG)

    assert forward == backward


def test_a_score_can_never_leave_zero_to_a_hundred() -> None:
    low = compute_mastery([answer(0, 3)], CONFIG)
    high = compute_mastery([answer(5, 3)], CONFIG)  # more than possible is capped

    assert low is not None and high is not None
    assert low.score == 0.0 and high.score == 100.0


def test_each_objective_is_scored_on_its_own_answers_so_a_weak_part_shows() -> None:
    result = compute_mastery(
        [answer(1), answer(1), answer(0, objective="o2"), answer(1, objective="o2"),
         answer(0, objective="o2")],
        CONFIG,
    )  # fmt: skip

    assert result is not None
    assert result.objectives == (
        ObjectiveScore("o1", 100.0, 2),
        ObjectiveScore("o2", pytest.approx(33.33, abs=0.01), 3),  # type: ignore[arg-type]
    )
    assert result.weak_objectives(CONFIG) == ("o2",)


def test_weak_objectives_are_listed_weakest_first() -> None:
    result = compute_mastery(
        [answer(0.5, objective="o3"), answer(0, objective="o2"), answer(1, objective="o1")], CONFIG
    )

    assert result is not None and result.weak_objectives(CONFIG) == ("o2", "o3")


@pytest.mark.parametrize(
    ("score", "band"),
    [(0, "needs_practice"), (69.99, "needs_practice"), (70, "progressing"), (89.99, "progressing"),
     (90, "mastered"), (100, "mastered")],
)  # fmt: skip
def test_the_bands_follow_the_two_thresholds(score: float, band: str) -> None:
    assert band_for(score, CONFIG) == band


def test_the_thresholds_are_configuration_not_code() -> None:
    strict = MasteryConfig(needs_practice_below=85, mastered_from=95)

    assert band_for(80, CONFIG) == "progressing"
    assert band_for(80, strict) == "needs_practice"


def test_few_answers_make_a_score_an_early_estimate() -> None:
    few = compute_mastery([answer(1), answer(1)], CONFIG)
    enough = compute_mastery([answer(1)] * 4, CONFIG)

    assert few is not None and enough is not None
    assert few.low_confidence is True and enough.low_confidence is False


@pytest.mark.parametrize(
    "kwargs",
    [
        {"needs_practice_below": 90, "mastered_from": 70},
        {"needs_practice_below": 70, "mastered_from": 70},
        {"needs_practice_below": 0},
        {"mastered_from": 101},
        {"recency_decay": 0},
        {"recency_decay": 1.5},
        {"min_answers": 0},
    ],
)
def test_nonsense_thresholds_are_refused(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        MasteryConfig(**kwargs)  # type: ignore[arg-type]


def test_the_defaults_come_from_settings_and_must_make_sense() -> None:
    settings = valid_local_settings()

    assert settings.mastery_needs_practice_below == 70 and settings.mastery_mastered_from == 90
    assert settings.mastery_recency_decay == 0.7 and settings.mastery_min_answers == 4
    assert ALGORITHM_VERSION == "weighted-recency/v1"
    with pytest.raises(ValueError, match="MASTERY_NEEDS_PRACTICE_BELOW"):
        valid_local_settings(mastery_needs_practice_below=95, mastery_mastered_from=90)


# --- The next step ----------------------------------------------------------------------------


def mastery(score: float, *, objectives: tuple[ObjectiveScore, ...] = ()) -> MasteryResult:
    return MasteryResult(
        score=score,
        band=band_for(score, CONFIG),
        attempts=1,
        answers=5,
        low_confidence=False,
        objectives=objectives,
    )


def topic(
    title: str,
    study: str = "not_started",
    *,
    m: MasteryResult | None = None,
    lesson: bool | None = None,
    pending: bool = False,
) -> TopicState:
    return TopicState(
        item_id=uuid4(),
        title=title,
        study=study,  # type: ignore[arg-type]
        has_lesson=study != "not_started" if lesson is None else lesson,
        mastery=m,
        pending_quiz_id=uuid4() if pending else None,
    )


def step(*topics: TopicState) -> Recommendation:
    return recommend(topics, CONFIG)


def test_a_roadmap_with_no_topics_has_nothing_to_do() -> None:
    assert step().action == "all_done"


def test_a_topic_that_needs_practice_comes_before_everything_else() -> None:
    a = topic("Variables", "completed", m=mastery(95))
    b = topic(
        "Ownership",
        "completed",
        m=mastery(52, objectives=(ObjectiveScore("o2", 30, 3), ObjectiveScore("o1", 80, 2))),
    )
    c = topic("Lifetimes", "not_started")

    result = step(a, b, c)

    assert result.action == "practice_quiz" and result.item_id == b.item_id
    assert result.objective_ids == ("o2",)  # only the objective that scored below the threshold
    assert result.review_lesson is True
    assert "52%" in result.reason and "Ownership" in result.reason


def test_a_low_score_asks_for_a_small_remedy_not_a_restart() -> None:
    result = step(topic("Ownership", "completed", m=mastery(20)), topic("Next", "not_started"))

    assert result.action == "practice_quiz"
    assert "no need to repeat the whole course" in result.reason


def test_the_weakest_topic_is_chosen_and_ties_go_to_the_earlier_one() -> None:
    first = topic("First", "completed", m=mastery(60))
    second = topic("Second", "completed", m=mastery(40))
    third = topic("Third", "completed", m=mastery(40))

    assert step(first, second, third).item_id == second.item_id


def test_a_practice_quiz_that_is_already_written_is_the_next_step() -> None:
    weak = topic("Ownership", "completed", m=mastery(50), pending=True)

    result = step(weak)

    assert result.action == "take_quiz" and result.quiz_id == weak.pending_quiz_id
    assert result.review_lesson is True


def test_a_studied_topic_that_was_never_checked_gets_a_quiz() -> None:
    result = step(topic("Done", "completed", m=mastery(95)), topic("Studied", "completed"))

    assert result.action == "take_quiz" and "Studied" in result.reason
    assert result.quiz_id is None  # a new quiz is to be written


def test_a_quiz_waiting_to_be_taken_is_offered_before_more_studying() -> None:
    waiting = topic("Waiting", "in_progress", pending=True)

    result = step(waiting, topic("Later", "not_started"))

    assert result.action == "take_quiz" and result.quiz_id == waiting.pending_quiz_id


def test_otherwise_it_is_the_topic_in_progress_then_the_first_not_started() -> None:
    a = topic("A", "completed", m=mastery(95))
    b = topic("B", "not_started")
    c = topic("C", "in_progress")

    assert step(a, b, c).item_id == c.item_id
    assert step(a, b).item_id == b.item_id
    assert step(a, c).action == "continue_studying"


def test_a_topic_that_is_progressing_gets_one_more_practice_quiz_lowest_first() -> None:
    a = topic("A", "completed", m=mastery(85))
    b = topic("B", "completed", m=mastery(75))
    c = topic("C", "completed", m=mastery(95))

    result = step(a, b, c)

    assert result.action == "practice_quiz" and result.item_id == b.item_id
    assert result.review_lesson is False and "75%" in result.reason


def test_a_topic_mastered_in_a_quiz_is_not_sent_back_to_be_started() -> None:
    known = topic("Known", "not_started", m=mastery(95), lesson=True)
    other = topic("Other", "not_started")

    assert step(known, other).item_id == other.item_id
    assert step(known).action == "all_done"


def test_the_band_follows_the_thresholds_it_is_asked_with() -> None:
    assert band_for_thresholds(85, 70, 90) == "progressing"
    assert band_for_thresholds(85, 90, 95) == "needs_practice"
    assert band_for_thresholds(85, 50, 80) == "mastered"
    assert band_for_thresholds(70, 70, 90) == "progressing"  # the lower edge is inclusive
    assert band_for_thresholds(90, 70, 90) == "mastered"  # and so is the upper


def test_when_everything_is_mastered_there_is_nothing_more_to_do() -> None:
    result = step(topic("A", "completed", m=mastery(95)), topic("B", "completed", m=mastery(92)))

    assert result.action == "all_done"


def test_the_recommendation_is_the_same_for_the_same_input() -> None:
    topics = (topic("A", "completed", m=mastery(60)), topic("B", "not_started"))

    assert recommend(topics, CONFIG) == recommend(topics, CONFIG)
