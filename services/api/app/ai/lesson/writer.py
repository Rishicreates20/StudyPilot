"""The Lesson Writer: ask for a lesson, check it in code, repair it once, or fail clearly.

Plain orchestration, like the roadmap planner: one call produces a draft; ``build_lesson`` and
``validate_lesson`` check it against the topic's real context; if anything is wrong, the full list
of broken rules goes back in a single repair call. A second failure raises ``LessonInvalid``: no
partial or unchecked lesson is ever returned, and no loop could spend without bound.
"""

import json
from dataclasses import dataclass

import structlog

from app.ai.calls import Observer, call_structured
from app.ai.lesson.context import LessonContext
from app.ai.lesson.prompts import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    render_repair_prompt,
    render_user_prompt,
)
from app.ai.lesson.schema import DraftLesson, Lesson
from app.ai.lesson.validation import LessonMetrics, build_lesson, measure, validate_lesson
from app.ai.provider import LLMInvalidOutput, LLMProvider, StructuredRequest, StructuredResult
from app.ai.violations import Violation

log = structlog.get_logger("app.ai.lesson")

_PATH_CODES = frozenset({"SCHEMA", "STRUCTURE"})


class LessonInvalid(Exception):
    """The model could not produce a lesson that passes the checks."""

    code = "LESSON_INVALID"
    retryable = False
    user_message = (
        "The AI couldn't produce a lesson that passed our quality checks this time. "
        "Please try again."
    )

    def __init__(self, violations: list[Violation]) -> None:
        super().__init__(f"{len(violations)} rule(s) broken")
        self.violations = violations


@dataclass(frozen=True)
class LessonOutcome:
    lesson: Lesson
    metrics: LessonMetrics
    prompt_version: str
    provider: str
    model_id: str
    synthetic: bool
    repaired: bool


async def write_lesson(
    provider: LLMProvider, context: LessonContext, *, observer: Observer | None = None
) -> LessonOutcome:
    request = StructuredRequest(
        system=SYSTEM_PROMPT,
        user=render_user_prompt(context),
        purpose="lesson.write",
        prompt_version=PROMPT_VERSION,
        input_data=context.input_data(),
    )
    violations: list[Violation]
    previous_answer: str | None = None
    try:
        first = await call_structured(provider, request, DraftLesson, observer)
    except LLMInvalidOutput as exc:
        violations = _schema_violations(
            exc, "The answer did not match the required JSON structure."
        )
    else:
        lesson, violations = _check(first, context)
        if lesson is not None and not violations:
            return _outcome(lesson, first, repaired=False)
        previous_answer = _compact(first.value)

    log.info(
        "lesson.repairing",
        violation_codes=sorted({v.code for v in violations}),
        # Where an answer did not fit the structure ("sections.1.blocks.0.text"): field paths only,
        # never any of the model's own words.
        paths=sorted({v.message.split(":")[0] for v in violations if v.code in _PATH_CODES})[:10],
    )
    repair = StructuredRequest(
        system=SYSTEM_PROMPT,
        user=render_repair_prompt(context, previous_answer, violations),
        purpose="lesson.repair",
        prompt_version=PROMPT_VERSION,
        input_data=context.input_data(),
    )
    try:
        second = await call_structured(provider, repair, DraftLesson, observer)
    except LLMInvalidOutput as exc:
        raise LessonInvalid(
            _schema_violations(exc, "The corrected answer was not valid JSON.")
        ) from None
    repaired, remaining = _check(second, context)
    if repaired is None or remaining:
        raise LessonInvalid(remaining)
    return _outcome(repaired, second, repaired=True)


def _check(
    result: StructuredResult[DraftLesson], context: LessonContext
) -> tuple[Lesson | None, list[Violation]]:
    lesson, violations = build_lesson(result.value)
    if lesson is None:
        return None, violations
    return lesson, validate_lesson(lesson, context)


def _schema_violations(error: LLMInvalidOutput, fallback: str) -> list[Violation]:
    return [Violation("SCHEMA", problem) for problem in error.problems] or [
        Violation("SCHEMA", fallback)
    ]


def _outcome(
    lesson: Lesson, result: StructuredResult[DraftLesson], *, repaired: bool
) -> LessonOutcome:
    return LessonOutcome(
        lesson=lesson,
        metrics=measure(lesson),
        prompt_version=PROMPT_VERSION,
        provider=result.provider,
        model_id=result.model_id,
        synthetic=result.synthetic,
        repaired=repaired,
    )


def _compact(draft: DraftLesson) -> str:
    return json.dumps(draft.model_dump(), ensure_ascii=False, separators=(",", ":"))
