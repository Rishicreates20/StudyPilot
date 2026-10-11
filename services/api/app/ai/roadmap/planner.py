"""The Planning Agent: ask for a roadmap, check it in code, repair it once, or fail clearly.

The orchestration is deliberately plain. One call produces a plan; ``validate_plan`` checks it
against the learner's real constraints; if it fails, the full list of broken rules goes back in a
single repair call. A second failure raises ``PlanInvalid``: no partial or unchecked plan is ever
returned, and there is no loop that could spend without bound.
"""

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import structlog

from app.ai.provider import (
    LLMError,
    LLMInvalidOutput,
    LLMProvider,
    StructuredRequest,
    StructuredResult,
)
from app.ai.roadmap.context import PlanningContext
from app.ai.roadmap.prompts import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    render_repair_prompt,
    render_user_prompt,
)
from app.ai.roadmap.schema import PlannedRoadmap
from app.ai.roadmap.validation import (
    PlanMetrics,
    Violation,
    measure,
    normalize_plan,
    validate_plan,
)

log = structlog.get_logger("app.ai.planner")


class PlanInvalid(Exception):
    """The model could not produce a plan that satisfies the learner's constraints."""

    code = "PLAN_INVALID"
    retryable = False
    user_message = (
        "The AI couldn't produce a plan that fits your schedule this time. "
        "Try again, or adjust your daily minutes or target date."
    )

    def __init__(self, violations: list[Violation]) -> None:
        super().__init__(f"{len(violations)} rule(s) broken")
        self.violations = violations


@dataclass(frozen=True)
class CallRecord:
    """One model call, for the usage ledger. Success and failure are both recorded."""

    purpose: str
    provider: str
    model_id: str
    prompt_version: str
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int
    finish_reason: str
    error_code: str | None = None


@dataclass(frozen=True)
class PlanOutcome:
    plan: PlannedRoadmap
    metrics: PlanMetrics
    prompt_version: str
    provider: str
    model_id: str
    synthetic: bool
    repaired: bool


Observer = Callable[[CallRecord], Awaitable[None]]


async def plan_roadmap(
    provider: LLMProvider, context: PlanningContext, *, observer: Observer | None = None
) -> PlanOutcome:
    request = StructuredRequest(
        system=SYSTEM_PROMPT,
        user=render_user_prompt(context),
        purpose="roadmap.plan",
        prompt_version=PROMPT_VERSION,
        input_data=context.input_data(),
    )
    violations: list[Violation]
    previous_answer: str | None = None
    try:
        first = await _call(provider, request, observer)
    except LLMInvalidOutput as exc:
        violations = [Violation("SCHEMA", problem) for problem in exc.problems] or [
            Violation("SCHEMA", "The answer did not match the required JSON structure.")
        ]
    else:
        plan = normalize_plan(first.value)
        violations = validate_plan(plan, context)
        if not violations:
            return _outcome(plan, first, repaired=False)
        previous_answer = _compact(plan)

    log.info("planner.repairing", violation_codes=sorted({v.code for v in violations}))
    repair = StructuredRequest(
        system=SYSTEM_PROMPT,
        user=render_repair_prompt(context, previous_answer, violations),
        purpose="roadmap.repair",
        prompt_version=PROMPT_VERSION,
        input_data=context.input_data(),
    )
    try:
        second = await _call(provider, repair, observer)
    except LLMInvalidOutput as exc:
        raise PlanInvalid(
            [Violation("SCHEMA", problem) for problem in exc.problems]
            or [Violation("SCHEMA", "The corrected answer was not valid JSON.")]
        ) from None
    repaired = normalize_plan(second.value)
    remaining = validate_plan(repaired, context)
    if remaining:
        raise PlanInvalid(remaining)
    return _outcome(repaired, second, repaired=True)


async def _call(
    provider: LLMProvider, request: StructuredRequest, observer: Observer | None
) -> StructuredResult[PlannedRoadmap]:
    try:
        result = await provider.generate_structured(request, PlannedRoadmap)
    except LLMError as exc:
        if observer is not None:
            await observer(
                CallRecord(
                    purpose=request.purpose,
                    provider=provider.name,
                    model_id="",
                    prompt_version=request.prompt_version,
                    input_tokens=None,
                    output_tokens=None,
                    latency_ms=0,
                    finish_reason="",
                    error_code=exc.code,
                )
            )
        raise
    if observer is not None:
        await observer(
            CallRecord(
                purpose=request.purpose,
                provider=result.provider,
                model_id=result.model_id,
                prompt_version=request.prompt_version,
                input_tokens=result.usage.input_tokens,
                output_tokens=result.usage.output_tokens,
                latency_ms=result.latency_ms,
                finish_reason=result.finish_reason,
            )
        )
    return result


def _outcome(
    plan: PlannedRoadmap, result: StructuredResult[PlannedRoadmap], *, repaired: bool
) -> PlanOutcome:
    return PlanOutcome(
        plan=plan,
        metrics=measure(plan),
        prompt_version=PROMPT_VERSION,
        provider=result.provider,
        model_id=result.model_id,
        synthetic=result.synthetic,
        repaired=repaired,
    )


def _compact(plan: PlannedRoadmap) -> str:
    return json.dumps(plan.model_dump(), ensure_ascii=False, separators=(",", ":"))
