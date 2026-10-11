"""The Quiz Writer: ask for a quiz, check it in code, repair it once, or fail clearly.

The same plain orchestration as the lesson writer and the roadmap planner: one call produces a
draft; ``build_quiz`` and ``validate_quiz`` check it against the topic's real context; if anything
is wrong, the full list of broken rules goes back in a single repair call. A second failure raises
``QuizInvalid``: no unchecked quiz is ever returned, and no loop could spend without bound.
"""

import json
from dataclasses import dataclass

import structlog

from app.ai.calls import Observer, call_structured
from app.ai.provider import LLMInvalidOutput, LLMProvider, StructuredRequest, StructuredResult
from app.ai.quiz.context import QuizContext
from app.ai.quiz.prompts import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    render_repair_prompt,
    render_user_prompt,
)
from app.ai.quiz.schema import BuiltQuiz, DraftQuiz
from app.ai.quiz.validation import build_quiz, validate_quiz
from app.ai.violations import Violation

log = structlog.get_logger("app.ai.quiz")

_PATH_CODES = frozenset({"SCHEMA", "STRUCTURE"})


class QuizInvalid(Exception):
    """The model could not produce a quiz that passes the checks."""

    code = "QUIZ_INVALID"
    retryable = False
    user_message = (
        "The AI couldn't produce a quiz that passed our quality checks this time. Please try again."
    )

    def __init__(self, violations: list[Violation]) -> None:
        super().__init__(f"{len(violations)} rule(s) broken")
        self.violations = violations


@dataclass(frozen=True)
class QuizOutcome:
    quiz: BuiltQuiz
    prompt_version: str
    provider: str
    model_id: str
    synthetic: bool
    repaired: bool


async def write_quiz(
    provider: LLMProvider, context: QuizContext, *, observer: Observer | None = None
) -> QuizOutcome:
    request = StructuredRequest(
        system=SYSTEM_PROMPT,
        user=render_user_prompt(context),
        purpose="quiz.write",
        prompt_version=PROMPT_VERSION,
        input_data=context.input_data(),
    )
    violations: list[Violation]
    previous_answer: str | None = None
    try:
        first = await call_structured(provider, request, DraftQuiz, observer)
    except LLMInvalidOutput as exc:
        violations = _schema_violations(
            exc, "The answer did not match the required JSON structure."
        )
    else:
        quiz, violations = _check(first, context)
        if quiz is not None and not violations:
            return _outcome(quiz, first, repaired=False)
        previous_answer = _compact(first.value)

    log.info(
        "quiz.repairing",
        violation_codes=sorted({v.code for v in violations}),
        # Where an answer did not fit the structure: field paths only, never the model's words.
        paths=sorted({v.message.split(":")[0] for v in violations if v.code in _PATH_CODES})[:10],
    )
    repair = StructuredRequest(
        system=SYSTEM_PROMPT,
        user=render_repair_prompt(context, previous_answer, violations),
        purpose="quiz.repair",
        prompt_version=PROMPT_VERSION,
        input_data=context.input_data(),
    )
    try:
        second = await call_structured(provider, repair, DraftQuiz, observer)
    except LLMInvalidOutput as exc:
        raise QuizInvalid(
            _schema_violations(exc, "The corrected answer was not valid JSON.")
        ) from None
    repaired, remaining = _check(second, context)
    if repaired is None or remaining:
        raise QuizInvalid(remaining)
    return _outcome(repaired, second, repaired=True)


def _check(
    result: StructuredResult[DraftQuiz], context: QuizContext
) -> tuple[BuiltQuiz | None, list[Violation]]:
    quiz, violations = build_quiz(result.value, context)
    if quiz is None:
        return None, violations
    return quiz, validate_quiz(quiz, context)


def _schema_violations(error: LLMInvalidOutput, fallback: str) -> list[Violation]:
    return [Violation("SCHEMA", problem) for problem in error.problems] or [
        Violation("SCHEMA", fallback)
    ]


def _outcome(
    quiz: BuiltQuiz, result: StructuredResult[DraftQuiz], *, repaired: bool
) -> QuizOutcome:
    return QuizOutcome(
        quiz=quiz,
        prompt_version=PROMPT_VERSION,
        provider=result.provider,
        model_id=result.model_id,
        synthetic=result.synthetic,
        repaired=repaired,
    )


def _compact(draft: DraftQuiz) -> str:
    return json.dumps(draft.model_dump(), ensure_ascii=False, separators=(",", ":"))
