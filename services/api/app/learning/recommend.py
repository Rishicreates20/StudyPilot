"""What to do next: a pure function of how each topic of a roadmap stands.

No model and no database (ADR-010, ADR-036). The rules, in order, are the whole behaviour:

1. **A topic that needs practice comes first** (the lowest score, then the earliest in the study
   order). The remedy is small and targeted: review that topic's lesson and take a short practice
   quiz on the objectives that scored lowest. A low score never restarts the course; if a quiz for
   it is already written but not taken, that quiz is the next step.
2. **A topic that was studied but never assessed** (the earliest one) gets a quiz, because a quiz is
   what turns "I read it" into "I know it".
3. **Otherwise keep studying**: the topic the learner is part-way through, else the first not yet
   finished. A topic already mastered in a quiz is not "unfinished": what was tested beats what was
   ticked off, so the learner is never sent back to start a topic they have shown they know.
4. **A topic that is progressing** (not yet mastered) gets one more practice quiz, lowest first.
5. **Everything mastered**: nothing more to do for now.

The reason is a sentence that names the evidence (a score, a count), so the learner can see why.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from app.learning.mastery import MasteryConfig, MasteryResult

Action = Literal["take_quiz", "practice_quiz", "continue_studying", "all_done"]
StudyState = Literal["not_started", "in_progress", "completed"]


@dataclass(frozen=True)
class TopicState:
    item_id: UUID
    title: str
    study: StudyState
    has_lesson: bool
    mastery: MasteryResult | None
    # A quiz that has been written for this topic and not yet taken.
    pending_quiz_id: UUID | None = None


@dataclass(frozen=True)
class Recommendation:
    action: Action
    reason: str
    item_id: UUID | None = None
    # The quiz to take now (action ``take_quiz`` for a quiz that already exists).
    quiz_id: UUID | None = None
    # The objectives a practice quiz should target, weakest first.
    objective_ids: tuple[str, ...] = ()
    # Also go back over the lesson (a topic that needs practice).
    review_lesson: bool = False


def _percent(score: float) -> str:
    return f"{round(score)}%"


def recommend(topics: Sequence[TopicState], config: MasteryConfig) -> Recommendation:
    """The one next step for a learner whose topics are ``topics``, in study order."""
    if not topics:
        return Recommendation(action="all_done", reason="This roadmap has no topics to study yet.")

    # 1. The weakest topic that needs practice.
    weak = [
        (index, topic)
        for index, topic in enumerate(topics)
        if topic.mastery is not None and topic.mastery.band == "needs_practice"
    ]
    if weak:
        _, topic = min(
            weak, key=lambda pair: (pair[1].mastery.score if pair[1].mastery else 0, pair[0])
        )
        mastery = topic.mastery
        if mastery is None:  # unreachable: `weak` only holds topics with a result
            raise RuntimeError("a weak topic has no mastery")
        objectives = mastery.weak_objectives(config) or tuple(o.id for o in mastery.objectives)
        evidence = f"You scored {_percent(mastery.score)} on “{topic.title}”"
        if topic.pending_quiz_id is not None:
            return Recommendation(
                action="take_quiz",
                item_id=topic.item_id,
                quiz_id=topic.pending_quiz_id,
                objective_ids=objectives,
                review_lesson=True,
                reason=f"{evidence}. A practice quiz is ready: go over the lesson, then take it.",
            )
        return Recommendation(
            action="practice_quiz",
            item_id=topic.item_id,
            objective_ids=objectives,
            review_lesson=True,
            reason=(
                f"{evidence}. Go over the lesson again, then take a short practice quiz on the "
                "parts that scored lowest: there is no need to repeat the whole course."
            ),
        )

    # 2. A topic that was studied but never assessed.
    for topic in topics:
        studied = topic.study == "completed" and topic.has_lesson
        if topic.mastery is None and (studied or topic.pending_quiz_id is not None):
            return Recommendation(
                action="take_quiz",
                item_id=topic.item_id,
                quiz_id=topic.pending_quiz_id,
                reason=(
                    f"You have studied “{topic.title}” but not checked it yet. "
                    "A short quiz shows what has stuck."
                ),
            )

    # 3. Keep studying.
    unfinished = [
        topic
        for topic in topics
        if topic.study != "completed" and not (topic.mastery and topic.mastery.band == "mastered")
    ]
    if unfinished:
        topic = next((t for t in unfinished if t.study == "in_progress"), unfinished[0])
        verb = "Pick up" if topic.study == "in_progress" else "Start"
        return Recommendation(
            action="continue_studying",
            item_id=topic.item_id,
            reason=f"{verb} “{topic.title}”: it is the next topic on your roadmap.",
        )

    # 4. A topic that is progressing but not mastered yet.
    progressing = [
        topic
        for topic in topics
        if topic.mastery is not None and topic.mastery.band == "progressing"
    ]
    if progressing:
        topic = min(progressing, key=lambda t: t.mastery.score if t.mastery else 0)
        mastery = topic.mastery
        if mastery is None:  # unreachable: `progressing` only holds topics with a result
            raise RuntimeError("a progressing topic has no mastery")
        return Recommendation(
            action="practice_quiz",
            item_id=topic.item_id,
            objective_ids=mastery.weak_objectives(config),
            reason=(
                f"You are at {_percent(mastery.score)} on “{topic.title}”. One more practice quiz "
                f"could take it past {round(config.mastered_from)}%."
            ),
        )

    # 5. Everything is studied and mastered.
    return Recommendation(
        action="all_done",
        reason="Every topic on your roadmap is mastered. Well done: revisit any topic "
        "whenever you like.",
    )
