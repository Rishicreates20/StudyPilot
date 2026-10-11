"""Builders for quiz tests: a context, a draft that satisfies it, and quizzes in a database."""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from psycopg.types.json import Jsonb

from app.ai.fake_quiz import sample_quiz
from app.ai.quiz.context import QuizContext, QuizObjective
from app.ai.quiz.schema import (
    BuiltMultipleChoice,
    BuiltQuiz,
    BuiltShortAnswer,
    BuiltTrueFalse,
    DraftQuiz,
)
from app.ai.quiz.validation import build_quiz
from support.database import admin
from support.lessons import Seeded, add_lesson_job, valid_lesson
from support.rows import _insert, add_lesson  # pyright: ignore[reportPrivateUsage]


def make_quiz_context(**overrides: Any) -> QuizContext:
    values: dict[str, Any] = {
        "goal_title": "Learn the Rust programming language",
        "level": "beginner",
        "language": "en",
        "topic_title": "Ownership and borrowing",
        "topic_description": "How Rust manages memory without a garbage collector.",
        "objectives": (
            QuizObjective("o1", "Explain what ownership means"),
            QuizObjective("o2", "Use references to borrow a value"),
        ),
        "lesson": valid_lesson(),
        "purpose": "check",
        "focus_objective_ids": (),
        "question_count": 5,
        "max_short_answers": 1,
        "previous_prompts": (),
        "shuffle_seed": "seed-1",
    }
    values.update(overrides)
    return QuizContext(**values)


def valid_quiz_draft(context: QuizContext | None = None) -> DraftQuiz:
    """A draft that passes every check for ``context`` (the built-in sample quiz)."""
    return sample_quiz((context or make_quiz_context()).input_data())


def valid_quiz(context: QuizContext | None = None) -> BuiltQuiz:
    context = context or make_quiz_context()
    quiz, violations = build_quiz(valid_quiz_draft(context), context)
    assert quiz is not None and violations == [], violations
    return quiz


def changed_quiz(draft: DraftQuiz, edit: Callable[[dict[str, Any]], None]) -> DraftQuiz:
    """A copy of ``draft`` after ``edit`` modified its plain-data form."""
    data = draft.model_dump()
    edit(data)
    return DraftQuiz.model_validate(data)


@dataclass(frozen=True)
class StoredQuiz:
    """A quiz written straight to the database, with what is needed to answer it."""

    quiz: uuid.UUID
    lesson: uuid.UUID
    questions: tuple[uuid.UUID, ...]
    # question id -> the id of the right option (multiple choice and true/false only)
    correct: dict[uuid.UUID, str]
    # question id -> the kind
    kinds: dict[uuid.UUID, str]


def add_stored_quiz(
    dsn: str,
    seeded: Seeded,
    item: uuid.UUID,
    *,
    purpose: str = "check",
    quiz: BuiltQuiz | None = None,
    lesson: uuid.UUID | None = None,
    is_synthetic: bool = True,
) -> StoredQuiz:
    """Write a lesson (if needed), a quiz job, the quiz, its questions and its answer keys."""
    built = quiz or valid_quiz()
    if lesson is None:
        lesson_job = add_lesson_job(dsn, seeded, item, status="completed")
        lesson = add_lesson(dsn, seeded.user, seeded.roadmap, item, lesson_job)
    job = admin(dsn).fetchone(
        "insert into public.generation_jobs (user_id, goal_id, item_id, job_type, status, stage,"
        " progress, finished_at) values (%s, %s, %s, 'quiz', 'completed', 'done', 100, now())"
        " returning id",
        (seeded.user, seeded.goal, item),
    )
    assert job is not None
    quiz_id = _insert(
        dsn,
        "quizzes",
        {
            "user_id": seeded.user,
            "roadmap_id": seeded.roadmap,
            "item_id": item,
            "lesson_id": lesson,
            "job_id": job["id"],
            "purpose": purpose,
            "focus_objective_ids": [],
            "title": built.title,
            "language": built.language,
            "question_count": len(built.questions),
            "prompt_version": "test/v1",
            "provider": "fake",
            "model_id": "fake-1",
            "is_synthetic": is_synthetic,
        },
    )
    questions: list[uuid.UUID] = []
    correct: dict[uuid.UUID, str] = {}
    kinds: dict[uuid.UUID, str] = {}
    for position, question in enumerate(built.questions, start=1):
        options = (
            None
            if isinstance(question, BuiltShortAnswer)
            else Jsonb([option.model_dump() for option in question.options])
        )
        question_id = _insert(
            dsn,
            "questions",
            {
                "user_id": seeded.user,
                "quiz_id": quiz_id,
                "position": position,
                "kind": question.kind,
                "prompt": question.prompt,
                "options": options,
                "objective_id": question.objective_id,
                "difficulty": question.difficulty,
                "max_points": question.max_points,
            },
        )
        questions.append(question_id)
        kinds[question_id] = question.kind
        if isinstance(question, BuiltShortAnswer):
            key: dict[str, Any] = {
                "rubric": Jsonb({"points": [p.model_dump() for p in question.rubric]}),
                "model_answer": question.model_answer,
            }
        else:
            assert isinstance(question, BuiltMultipleChoice | BuiltTrueFalse)
            correct[question_id] = question.correct_option_id
            key = {"correct_option_id": question.correct_option_id}
        admin(dsn).execute(
            "insert into public.question_answer_keys (question_id, user_id, correct_option_id,"
            " rubric, model_answer, explanation, option_notes) values (%s, %s, %s, %s, %s, %s, %s)",
            (
                question_id,
                seeded.user,
                key.get("correct_option_id"),
                key.get("rubric"),
                key.get("model_answer"),
                question.explanation,
                Jsonb(getattr(question, "option_notes", {})),
            ),
        )
    return StoredQuiz(quiz_id, lesson, tuple(questions), correct, kinds)


def wrong_option(dsn: str, question: uuid.UUID, correct: str) -> str:
    """An option id of ``question`` that is not the right one."""
    options = admin(dsn).scalar("select options from public.questions where id = %s", (question,))
    return next(option["id"] for option in options if option["id"] != correct)
