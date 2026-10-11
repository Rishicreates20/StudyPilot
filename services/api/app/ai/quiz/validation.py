"""Turns a model's draft quiz into stored questions, and checks them in code.

A draft can be perfectly well-formed JSON and still be a bad quiz: an answer key that points at a
different option than the one it names, two questions that ask the same thing, an option that says
"all of the above", a question that tests nothing on the roadmap, an explanation that defends the
wrong answer. ``build_quiz`` and ``validate_quiz`` catch these deterministically and report *every*
problem worded as an instruction, so the writer can hand the whole list back for one repair
attempt. Nothing here asks a model whether its own quiz is good, and nothing quotes the model's
words back (problems say *where*, e.g. "Question 3").

What code can and cannot promise: it can check structure, uniqueness, the answer key, the mapping to
the roadmap's objectives, near-duplicates, banned phrasings, and the obvious ways an explanation
contradicts its key. It cannot check that a question is *correct* or *well taught*; that is why a
quiz comes from the lesson the learner studied, is labelled as machine-written, and why results
always show the explanation next to the answer.
"""

import random
import re
from collections import Counter
from collections.abc import Iterator
from typing import Any

from pydantic import ValidationError

from app.ai.quiz.context import QuizContext
from app.ai.quiz.schema import (
    BuiltMultipleChoice,
    BuiltQuestion,
    BuiltQuiz,
    BuiltShortAnswer,
    DraftQuestion,
    DraftQuiz,
)
from app.ai.violations import Violation

_MAX_REPORTED = 25
_MIN_PROMPT_CHARS = 10
# Two questions (or two options) this alike, by shared words, are treated as the same.
_NEAR_DUPLICATE_QUESTION = 0.8
_NEAR_DUPLICATE_OPTION = 0.9
# An answer this long, found word for word inside the question, gives the answer away.
_MIN_LEAK_CHARS = 12
_OPTION_IDS = "abcd"

_URL_RE = re.compile(r"(?:https?://|ftp://|www\.)\S+", re.IGNORECASE)
# "All of the above", "none of these", "both A and B": options that depend on other options are
# ambiguous (and make a key hard to check).
_DEPENDENT_OPTION_RE = re.compile(
    r"\b(?:all|none|both|neither)\s+of\s+(?:the\s+)?(?:above|these|them|those)\b"
    r"|\b(?:a|b|c|d)\s*(?:and|&|,)\s*(?:a|b|c|d)\s+(?:are|is)\b"
    r"|\bboth\s+(?:a|b|c|d)\s+and\s+(?:a|b|c|d)\b",
    re.IGNORECASE,
)
_WORD_RE = re.compile(r"[\W_]+", re.UNICODE)


def normalize(text: str) -> str:
    """Lower-cased text with punctuation and runs of space collapsed, for comparing."""
    return _WORD_RE.sub(" ", text.casefold()).strip()


def _words(text: str) -> frozenset[str]:
    return frozenset(normalize(text).split())


def similarity(a: str, b: str) -> float:
    """Shared words over all words (0 to 1)."""
    first, second = _words(a), _words(b)
    if not first or not second:
        return 0.0
    return len(first & second) / len(first | second)


def _add(found: list[Violation], code: str, message: str) -> None:
    found.append(Violation(code, message))


def _convert(
    question: DraftQuestion, number: int, context: QuizContext, found: list[Violation]
) -> dict[str, Any] | None:
    """One draft question in the stored shape (a plain dict, validated with the whole quiz)."""
    where = f"Question {number}"
    base: dict[str, Any] = {
        "kind": question.kind,
        "prompt": question.prompt,
        "objective_id": question.objective_id.strip(),
        "difficulty": question.difficulty,
        "explanation": question.explanation,
    }

    if question.kind == "true_false":
        answer = normalize(question.correct_option)
        if answer not in {"true", "false"}:
            _add(
                found,
                "ANSWER_KEY",
                f'{where} is true/false: correct_option must be "true" or "false".',
            )
            return None
        return {
            **base,
            "options": [{"id": "true", "text": "True"}, {"id": "false", "text": "False"}],
            "correct_option_id": answer,
        }

    if question.kind == "short_answer":
        rubric = [point for point in question.rubric if point.text.strip()]
        if not 2 <= len(rubric) <= 5:
            _add(found, "RUBRIC", f"{where} is a short answer: give a rubric of 2 to 5 points.")
            return None
        if not question.model_answer.strip():
            _add(found, "RUBRIC", f"{where} is a short answer: give a model answer.")
            return None
        return {
            **base,
            "rubric": [
                {"id": f"p{index}", "text": point.text, "points": point.points}
                for index, point in enumerate(rubric, start=1)
            ],
            "model_answer": question.model_answer,
        }

    options = [option.strip() for option in question.options]
    if len(options) != len(_OPTION_IDS) or not all(options):
        _add(found, "OPTIONS", f"{where} must have exactly 4 non-empty options.")
        return None
    keys = [normalize(option) for option in options]
    if len(set(keys)) != len(keys):
        _add(
            found,
            "DUPLICATE_OPTION",
            f"{where} has two options that are the same. Make each different.",
        )
        return None
    matches = [index for index, key in enumerate(keys) if key == normalize(question.correct_option)]
    if len(matches) != 1:
        _add(
            found,
            "ANSWER_KEY",
            f"{where}: correct_option must be the exact text of exactly one of its options.",
        )
        return None

    # Shuffle so the right answer is not always in the same place; the seed makes it repeatable.
    order = list(range(len(options)))
    # A seeded shuffle for repeatability, not for security.
    random.Random(f"{context.shuffle_seed}:{number}").shuffle(order)  # noqa: S311
    notes: dict[str, str] = {}
    if len(question.option_notes) == len(options):
        for position, original in enumerate(order):
            note = question.option_notes[original].strip()
            if note:
                notes[_OPTION_IDS[position]] = note
    return {
        **base,
        "options": [
            {"id": _OPTION_IDS[position], "text": options[original]}
            for position, original in enumerate(order)
        ],
        "correct_option_id": _OPTION_IDS[order.index(matches[0])],
        "option_notes": notes,
    }


def build_quiz(draft: DraftQuiz, context: QuizContext) -> tuple[BuiltQuiz | None, list[Violation]]:
    """The stored quiz for ``draft``, or the list of what is wrong with it."""
    found: list[Violation] = []
    questions: list[dict[str, Any]] = []
    for number, question in enumerate(draft.questions, start=1):
        converted = _convert(question, number, context, found)
        if converted is not None:
            questions.append(converted)
    if found:
        return None, found
    try:
        quiz = BuiltQuiz.model_validate(
            {
                "language": draft.language.strip().lower(),
                "title": draft.title,
                "questions": questions,
            }
        )
    except ValidationError as exc:
        problems = [
            Violation(
                "STRUCTURE",
                f"{'.'.join(str(part) for part in error['loc']) or 'quiz'}: {error['msg']}",
            )
            for error in exc.errors(include_input=False, include_url=False)
        ]
        return None, problems[:_MAX_REPORTED]
    return quiz, []


def _texts(question: BuiltQuestion) -> Iterator[str]:
    """Every piece of learner-visible or feedback text of a question."""
    yield question.prompt
    yield question.explanation
    if isinstance(question, BuiltShortAnswer):
        yield question.model_answer
        for point in question.rubric:
            yield point.text
    else:
        for option in question.options:
            yield option.text
        if isinstance(question, BuiltMultipleChoice):
            yield from question.option_notes.values()


def validate_quiz(quiz: BuiltQuiz, context: QuizContext) -> list[Violation]:
    """Every rule the quiz breaks, or an empty list when it is acceptable."""
    found: list[Violation] = []
    questions = quiz.questions

    if quiz.language != context.language:
        _add(
            found,
            "LANGUAGE",
            f'The quiz is written in "{quiz.language}", but it must be written in '
            f'"{context.language}", the language of the learner\'s roadmap.',
        )
    if len(questions) != context.question_count:
        _add(
            found,
            "COUNT",
            f"The quiz has {len(questions)} questions; write exactly {context.question_count}.",
        )

    shorts = sum(isinstance(q, BuiltShortAnswer) for q in questions)
    if shorts > context.max_short_answers:
        _add(
            found,
            "KIND_MIX",
            f"The quiz has {shorts} short-answer questions; use at most "
            f"{context.max_short_answers}.",
        )
    if not any(isinstance(q, BuiltMultipleChoice) for q in questions):
        _add(found, "KIND_MIX", "Include at least one multiple-choice question.")

    allowed = context.objective_ids
    focus = set(context.focus_objective_ids)
    for number, question in enumerate(questions, start=1):
        if question.objective_id not in allowed:
            _add(
                found,
                "OBJECTIVE",
                f'Question {number} tests objective "{question.objective_id}", which is not one of '
                f"this topic's objectives ({', '.join(sorted(allowed))}). "
                "Use an id from the input.",
            )
        elif focus and question.objective_id not in focus:
            _add(
                found,
                "OBJECTIVE_FOCUS",
                f'Question {number} tests "{question.objective_id}", but this practice quiz must '
                f"only test: {', '.join(sorted(focus))}.",
            )
    targets = context.target_objective_ids
    covered = {q.objective_id for q in questions}
    if len(targets) <= len(questions):
        missing = [target for target in targets if target not in covered]
        if missing:
            _add(
                found,
                "COVERAGE",
                f"No question tests objective(s) {', '.join(missing)}. Cover every "
                "objective listed as a target.",
            )

    _check_duplicates(questions, context, found)
    _check_wording(questions, found)

    if len(questions) >= 4 and len({q.difficulty for q in questions}) < 2:
        _add(
            found,
            "DIFFICULTY_MIX",
            "Mix the difficulty: use at least two of easy, medium and hard.",
        )
    return found[:_MAX_REPORTED]


def _check_duplicates(
    questions: list[BuiltQuestion], context: QuizContext, found: list[Violation]
) -> None:
    for first in range(len(questions)):
        for second in range(first + 1, len(questions)):
            if (
                similarity(questions[first].prompt, questions[second].prompt)
                >= _NEAR_DUPLICATE_QUESTION
            ):
                _add(
                    found,
                    "DUPLICATE",
                    f"Questions {first + 1} and {second + 1} ask the same thing. "
                    "Ask something different.",
                )
    for number, question in enumerate(questions, start=1):
        for earlier in context.previous_prompts:
            if similarity(question.prompt, earlier) >= _NEAR_DUPLICATE_QUESTION:
                _add(
                    found,
                    "REPEATS_EARLIER",
                    f"Question {number} repeats a question from an earlier quiz on this topic "
                    "(listed under do_not_repeat). Ask something new.",
                )
                break


def _check_wording(questions: list[BuiltQuestion], found: list[Violation]) -> None:
    counts = Counter(normalize(q.prompt) for q in questions)
    for number, question in enumerate(questions, start=1):
        if (
            len(question.prompt.strip()) < _MIN_PROMPT_CHARS
            or counts[normalize(question.prompt)] > 1
        ):
            _add(
                found,
                "VAGUE",
                f"Question {number} is too short or repeated: ask a complete question.",
            )
        for text in _texts(question):
            if _URL_RE.search(text):
                _add(
                    found,
                    "LINK",
                    f"Question {number} contains a web address. Remove it: links cannot "
                    "be checked.",
                )
                break
        if isinstance(question, BuiltMultipleChoice):
            _check_multiple_choice(question, number, found)


def _check_multiple_choice(
    question: BuiltMultipleChoice, number: int, found: list[Violation]
) -> None:
    texts = {option.id: option.text for option in question.options}
    for option in question.options:
        if _DEPENDENT_OPTION_RE.search(option.text):
            _add(
                found,
                "AMBIGUOUS",
                f"Question {number} has an option that refers to other options "
                '("all of the above", "both A and B"). Make every option stand on its own.',
            )
            break
    ids = list(texts)
    if any(
        similarity(texts[a], texts[b]) >= _NEAR_DUPLICATE_OPTION
        for index, a in enumerate(ids)
        for b in ids[index + 1 :]
    ):
        _add(
            found,
            "AMBIGUOUS",
            f"Question {number} has two options that say nearly the same thing. "
            "Make them clearly different.",
        )

    correct = texts[question.correct_option_id]
    if len(correct) >= _MIN_LEAK_CHARS and normalize(correct) in normalize(question.prompt):
        _add(
            found,
            "ANSWER_LEAK",
            f"Question {number} contains its own answer word for word. Rephrase the question.",
        )
    # An explanation that names a wrong option and never the right one defends the wrong answer.
    explanation = normalize(question.explanation)
    if normalize(correct) not in explanation:
        for option_id, text in texts.items():
            if (
                option_id != question.correct_option_id
                and len(text) >= _MIN_LEAK_CHARS
                and normalize(text) in explanation
            ):
                _add(
                    found,
                    "EXPLANATION_CONFLICT",
                    f"The explanation of question {number} seems to support a different option "
                    "than the answer key. Make the explanation back the correct option.",
                )
                break
