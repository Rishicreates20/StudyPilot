"""Make ONE real call to the configured AI provider and report whether it works.

    uv run --directory services/api python -m scripts.llm_smoke                 # plan a roadmap
    uv run --directory services/api python -m scripts.llm_smoke lesson          # write a lesson
    uv run --directory services/api python -m scripts.llm_smoke lesson --show   # ...and print it

It reads ``services/api/.env`` exactly like the API and the worker do, runs a small fixed example
through the real planner or lesson writer (prompt, schema, validation and, if needed, the one
repair), and prints a short report. It does not touch the database and never prints the API key or
the prompt; a failure shows the error code and a short, key-free detail. ``--show`` also prints the
lesson that PASSED validation, so a person can judge its quality (an unchecked answer never is).

Use it after setting ``LLM_PROVIDER=gemini`` and ``GEMINI_API_KEY`` to check the live path. A real
call uses a small amount of the provider's quota.
"""

import asyncio
import sys
from datetime import UTC, datetime
from uuid import uuid4

import httpx2

from app.ai.calls import CallRecord
from app.ai.factory import build_provider
from app.ai.lesson.context import TopicFacts
from app.ai.lesson.context import build_context as build_lesson_context
from app.ai.lesson.schema import CalloutBlock, CodeBlock, Lesson, ListBlock, ParagraphBlock
from app.ai.lesson.writer import LessonInvalid, write_lesson
from app.ai.provider import LLMError, LLMProvider
from app.ai.roadmap.context import build_context, readiness_problems
from app.ai.roadmap.planner import PlanInvalid, plan_roadmap
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


def example_topic() -> TopicFacts:
    """A topic from the example goal's roadmap: the second one, with one before and one after."""
    return TopicFacts(
        item_id=uuid4(),
        roadmap_id=uuid4(),
        roadmap_status="current",
        kind="topic",
        title="Ownership and borrowing",
        description="How Rust decides who is responsible for a value, and how others may use it.",
        practice_task="Write a function that takes a string by reference and returns its length.",
        estimated_minutes=40,
        module_title="Core ideas",
        module_summary="The ideas the rest of Rust rests on.",
        objectives=("Explain ownership and borrowing in your own words",),
        language="en",
        syllabus_basis="general_knowledge",
        earlier_titles=("Installing Rust and writing Hello, world",),
        later_titles=("Structs and enums",),
    )


async def run_lesson(provider: LLMProvider, *, show: bool = False) -> int:
    """Write the example lesson. Returns the exit code (0 = the writer produced a valid lesson)."""
    context = build_lesson_context(example_goal(), example_topic())
    calls: list[CallRecord] = []

    async def observe(record: CallRecord) -> None:
        calls.append(record)

    try:
        outcome = await write_lesson(provider, context, observer=observe)
    except LessonInvalid as invalid:
        print(f"FAILED: the model's lesson broke {len(invalid.violations)} rule(s) twice:")
        for violation in invalid.violations:
            print(f"  - {violation.code}: {violation.message}")
        _print_calls(calls)
        return 1
    except LLMError as error:
        print(f"FAILED: {error.code} (retryable: {error.retryable})")
        print(f"  detail: {error.detail or '(none)'}")
        _print_calls(calls)
        return 1

    lesson, metrics = outcome.lesson, outcome.metrics
    print(f"OK: {outcome.provider} / {outcome.model_id} produced a valid lesson")
    print(f"  title:        {lesson.title}")
    print(
        f"  structure:    {metrics.sections} sections, {metrics.words} words "
        f"(aim {context.target_words}), {metrics.code_blocks} code blocks,"
    )
    print(
        f"                {metrics.examples} worked examples, {len(lesson.definitions)} key terms, "
        f"{len(lesson.common_misconceptions)} common mistakes"
    )
    print(f"  sources:      {len(lesson.source_references)} (none were supplied)")
    print(f"  repaired:     {'yes (the first answer broke a rule)' if outcome.repaired else 'no'}")
    print(
        f"  synthetic:    {'yes: a test double, not a real model' if outcome.synthetic else 'no'}"
    )
    _print_calls(calls)
    if show:
        _print_lesson(lesson)
    return 0


def _print_lesson(lesson: Lesson) -> None:
    fence = "`" * 3
    print("\n" + "=" * 78)
    print(lesson.title)
    print("=" * 78)
    print("\nYou will learn:")
    for objective in lesson.learning_objectives:
        print(f"  - {objective}")
    for section in lesson.sections:
        print(f"\n## {section.heading}")
        for block in section.blocks:
            if isinstance(block, ParagraphBlock):
                print(f"\n{block.text}")
            elif isinstance(block, ListBlock):
                for number, item in enumerate(block.items, start=1):
                    print(f"  {f'{number}.' if block.ordered else '-'} {item}")
            elif isinstance(block, CodeBlock):
                print(f"\n{fence}{block.language}\n{block.code}\n{fence}")
            elif isinstance(block, CalloutBlock):
                print(f"\n[{block.kind.upper()}] {block.title or ''} {block.text}")
    print("\n## Key terms")
    for definition in lesson.definitions:
        print(f"  {definition.term}: {definition.meaning}")
    print("\n## Worked examples")
    for example in lesson.worked_examples:
        print(f"  {example.title}\n    Problem: {example.problem}")
        for step in example.steps:
            print(f"    - {step}")
        print(f"    Result: {example.answer}")
    print("\n## Common mistakes")
    for mistake in lesson.common_misconceptions:
        print(f"  Believed: {mistake.misconception}\n  Actually: {mistake.correction}")
    print("\n## Summary")
    for point in lesson.summary:
        print(f"  - {point}")
    print("\n## In simple words")
    for paragraph in lesson.simple_explanation.paragraphs:
        print(f"  {paragraph}")
    if lesson.simple_explanation.analogy:
        print(f"  Like: {lesson.simple_explanation.analogy}")


async def main(settings: Settings, *, lesson: bool = False, show: bool = False) -> int:
    async with httpx2.AsyncClient() as client:
        try:
            provider = build_provider(settings, client)
        except LLMError as error:
            print(f"Not configured: {error.detail}. Set LLM_PROVIDER (and GEMINI_API_KEY) in .env.")
            return 2
        return await (run_lesson(provider, show=show) if lesson else run(provider))


if __name__ == "__main__":
    # psycopg is not used here, but the project's other entry points select this loop on Windows.
    arguments = sys.argv[1:]
    sys.exit(
        asyncio.run(
            main(load_settings_or_exit(), lesson="lesson" in arguments, show="--show" in arguments),
            loop_factory=asyncio.SelectorEventLoop,
        )
    )
