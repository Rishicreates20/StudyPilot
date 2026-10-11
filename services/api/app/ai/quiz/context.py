"""The facts a quiz is written from: the topic's lesson, its objectives, and what was asked before.

Built once per job and used twice: rendered into the prompt, and handed to the validator, so the
rules the quiz is checked against are the same facts the model was given.
"""

from dataclasses import dataclass
from typing import Any, Literal

from app.ai.lesson.schema import (
    CalloutBlock,
    Lesson,
    ListBlock,
    ParagraphBlock,
)
from app.schemas.goals import Goal

Purpose = Literal["check", "practice"]


@dataclass(frozen=True)
class QuizObjective:
    id: str
    text: str


@dataclass(frozen=True)
class QuizContext:
    goal_title: str
    level: str
    language: str
    topic_title: str
    topic_description: str
    # The roadmap objectives this topic serves: the only ids a question may name.
    objectives: tuple[QuizObjective, ...]
    # What the quiz is written from: the topic's current lesson.
    lesson: Lesson
    purpose: Purpose
    # For a practice quiz: the objectives that scored lowest. Empty for a check quiz.
    focus_objective_ids: tuple[str, ...]
    question_count: int
    max_short_answers: int
    # The prompts of earlier quizzes on this topic, so none is repeated. Never any answers.
    previous_prompts: tuple[str, ...] = ()
    # Makes the shuffle of the options repeatable (the job's id).
    shuffle_seed: str = ""

    @property
    def objective_ids(self) -> frozenset[str]:
        return frozenset(objective.id for objective in self.objectives)

    @property
    def target_objective_ids(self) -> tuple[str, ...]:
        """The objectives the quiz should cover: the focus of a practice quiz, else all."""
        if self.focus_objective_ids:
            return self.focus_objective_ids
        return tuple(objective.id for objective in self.objectives)

    def input_data(self) -> dict[str, Any]:
        """The facts as plain data: rendered into the prompt, and used by the test double."""
        return {
            "goal": {"title": self.goal_title, "level": self.level},
            "language": self.language,
            "topic": {"title": self.topic_title, "description": self.topic_description},
            "objectives": [{"id": o.id, "text": o.text} for o in self.objectives],
            "purpose": self.purpose,
            "focus_objective_ids": list(self.focus_objective_ids),
            "quiz": {
                "question_count": self.question_count,
                "max_short_answers": self.max_short_answers,
            },
            "lesson": lesson_digest(self.lesson),
            "do_not_repeat": list(self.previous_prompts),
        }


def lesson_digest(lesson: Lesson) -> dict[str, Any]:
    """The lesson's teaching content as compact data (no ids, no simple explanation)."""
    sections: list[dict[str, Any]] = []
    for section in lesson.sections:
        text: list[str] = []
        for block in section.blocks:
            if isinstance(block, ParagraphBlock | CalloutBlock):
                text.append(block.text)
            elif isinstance(block, ListBlock):
                text.extend(block.items)
            else:
                text.append(f"[{block.language} code] {block.code}")
        sections.append({"heading": section.heading, "text": text})
    return {
        "title": lesson.title,
        "objectives": list(lesson.learning_objectives),
        "sections": sections,
        "key_terms": [{"term": d.term, "meaning": d.meaning} for d in lesson.definitions],
        "worked_examples": [
            {"title": e.title, "problem": e.problem, "steps": list(e.steps), "answer": e.answer}
            for e in lesson.worked_examples
        ],
        "common_mistakes": [
            {"mistake": m.misconception, "truth": m.correction}
            for m in lesson.common_misconceptions
        ],
        "summary": list(lesson.summary),
    }


def build_context(
    goal: Goal,
    *,
    topic_title: str,
    topic_description: str,
    objectives: tuple[QuizObjective, ...],
    lesson: Lesson,
    language: str,
    purpose: Purpose,
    focus_objective_ids: tuple[str, ...],
    question_count: int,
    max_short_answers: int,
    previous_prompts: tuple[str, ...],
    shuffle_seed: str,
) -> QuizContext:
    return QuizContext(
        goal_title=goal.title,
        level=goal.current_level,
        language=language,
        topic_title=topic_title,
        topic_description=topic_description,
        objectives=objectives,
        lesson=lesson,
        purpose=purpose,
        focus_objective_ids=focus_objective_ids,
        question_count=question_count,
        max_short_answers=max_short_answers,
        previous_prompts=previous_prompts,
        shuffle_seed=shuffle_seed,
    )
