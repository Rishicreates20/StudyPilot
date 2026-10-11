"""Make ONE real call to the configured AI provider and report whether roadmap planning works.

    uv run --directory services/api python -m scripts.llm_smoke

It reads ``services/api/.env`` exactly like the API and the worker do, plans a roadmap for a small
fixed example goal through the real planner (prompt, schema, validation and, if needed, the one
repair), and prints a short report. It does not touch the database and never prints the API key,
the prompt or the model's raw output; a failure shows the error code and a short, key-free detail.

Use it after setting ``LLM_PROVIDER=gemini`` and ``GEMINI_API_KEY`` to check the live path. A real
call uses a small amount of the provider's quota.
"""

import asyncio
import sys
from datetime import UTC, datetime
from uuid import uuid4

import httpx2

from app.ai.factory import build_provider
from app.ai.provider import LLMError, LLMProvider
from app.ai.roadmap.context import build_context, readiness_problems
from app.ai.roadmap.planner import CallRecord, PlanInvalid, plan_roadmap
from app.core.config import Settings, load_settings_or_exit
from app.schemas.goals import Goal


def example_goal() -> Goal:
    now = datetime.now(UTC)
    return Goal(
        id=uuid4(),
        title="Learn the Rust programming language",
        description="I know Python and want to write small command-line tools.",
        goal_type="professional_skill",
        current_level="beginner",
        target_date=None,
        daily_minutes=60,
        preferred_languages=["en"],
        learning_preferences=["examples", "quizzes", "revision"],
        status="active",
        completed_at=None,
        archived_at=None,
        created_at=now,
        updated_at=now,
    )


async def run(provider: LLMProvider) -> int:
    """Plan the example goal. Returns the process exit code (0 = the planner produced a plan)."""
    goal = example_goal()
    today = datetime.now(UTC).date()
    if problems := readiness_problems(goal, today):  # the fixed example is plannable; be safe
        print(f"The example goal is not plannable: {problems[0]}")
        return 2
    context = build_context(goal, today=today)

    calls: list[CallRecord] = []

    async def observe(record: CallRecord) -> None:
        calls.append(record)

    try:
        outcome = await plan_roadmap(provider, context, observer=observe)
    except PlanInvalid as invalid:
        print(f"FAILED: the model's plan broke {len(invalid.violations)} rule(s) twice:")
        for violation in invalid.violations:
            print(f"  - {violation.code}: {violation.message}")
        _print_calls(calls)
        return 1
    except LLMError as error:
        print(f"FAILED: {error.code} (retryable: {error.retryable})")
        print(f"  detail: {error.detail or '(none)'}")
        _print_calls(calls)
        return 1

    plan, metrics = outcome.plan, outcome.metrics
    print(f"OK: {outcome.provider} / {outcome.model_id} produced a valid plan")
    print(f"  title:        {plan.title}")
    print(f"  language:     {plan.language}   basis: {plan.syllabus_basis}")
    print(
        f"  structure:    {len(plan.modules)} modules, {metrics.topic_count} topics, "
        f"{len(plan.revision_sessions)} revision sessions, {len(plan.enrichment)} optional"
    )
    print(
        f"  schedule:     {metrics.total_minutes} minutes over {metrics.total_days} days "
        f"(limit {context.daily_minutes} a day)"
    )
    print(f"  repaired:     {'yes (the first answer broke a rule)' if outcome.repaired else 'no'}")
    print(
        f"  synthetic:    {'yes: a test double, not a real model' if outcome.synthetic else 'no'}"
    )
    _print_calls(calls)
    return 0


def _print_calls(calls: list[CallRecord]) -> None:
    for record in calls:
        tokens = (
            f"{record.input_tokens} in / {record.output_tokens} out"
            if record.input_tokens is not None
            else "tokens unknown"
        )
        result = record.error_code or f"finish={record.finish_reason}"
        print(f"  call {record.purpose}: {result}, {tokens}, {record.latency_ms} ms")


async def main(settings: Settings) -> int:
    async with httpx2.AsyncClient() as client:
        try:
            provider = build_provider(settings, client)
        except LLMError as error:
            print(f"Not configured: {error.detail}. Set LLM_PROVIDER (and GEMINI_API_KEY) in .env.")
            return 2
        return await run(provider)


if __name__ == "__main__":
    # psycopg is not used here, but the project's other entry points select this loop on Windows.
    sys.exit(asyncio.run(main(load_settings_or_exit()), loop_factory=asyncio.SelectorEventLoop))
