"""The live-check script: its report must be honest and must never leak anything."""

import pytest

from app.ai.fake import FakeProvider
from app.ai.fake_roadmap import roadmap_responder
from app.ai.provider import LLMRateLimited
from scripts.llm_smoke import example_goal, run

pytestmark = pytest.mark.anyio


async def test_a_working_provider_gets_a_clear_ok_report(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = await run(FakeProvider(roadmap_responder))

    report = capsys.readouterr().out
    assert code == 0
    assert report.startswith("OK: fake / fake-planner-1")
    assert "synthetic:    yes" in report  # a stand-in says so
    assert "call roadmap.plan: finish=STOP" in report


async def test_a_provider_error_is_reported_with_its_code_and_a_nonzero_exit(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = await run(FakeProvider(script=[LLMRateLimited("HTTP 429: quota")]))

    report = capsys.readouterr().out
    assert code == 1
    assert "FAILED: AI_RATE_LIMITED (retryable: True)" in report
    assert "HTTP 429: quota" in report


async def test_an_unfixable_plan_lists_the_broken_rules(capsys: pytest.CaptureFixture[str]) -> None:
    code = await run(FakeProvider(script=[{"title": "nonsense"}, {"title": "still nonsense"}]))

    report = capsys.readouterr().out
    assert code == 1
    assert "broke" in report and "SCHEMA" in report


def test_the_example_goal_is_a_valid_plannable_goal() -> None:
    goal = example_goal()

    assert goal.status == "active"
    assert goal.daily_minutes == 60
    assert goal.preferred_languages == ["en"]


# --- The lesson check ------------------------------------------------------------------------


async def test_a_working_provider_gets_a_clear_lesson_report(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from app.ai.factory import builtin_responder
    from scripts.llm_smoke import run_lesson

    code = await run_lesson(FakeProvider(builtin_responder))

    report = capsys.readouterr().out
    assert code == 0
    assert report.startswith("OK: fake / fake-planner-1 produced a valid lesson")
    assert "synthetic:    yes" in report
    assert "call lesson.write: finish=STOP" in report
    assert "In simple words" not in report  # the lesson itself is only printed on request


async def test_the_lesson_itself_is_printed_on_request_and_only_once_it_passed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from app.ai.factory import builtin_responder
    from scripts.llm_smoke import run_lesson

    code = await run_lesson(FakeProvider(builtin_responder), show=True)

    report = capsys.readouterr().out
    assert code == 0
    assert "## In simple words" in report and "## Worked examples" in report
    assert "Sample lesson: Ownership and borrowing" in report


async def test_a_lesson_provider_error_is_reported_with_its_code(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts.llm_smoke import run_lesson

    code = await run_lesson(FakeProvider(script=[LLMRateLimited("HTTP 429: quota")]))

    report = capsys.readouterr().out
    assert code == 1
    assert "FAILED: AI_RATE_LIMITED (retryable: True)" in report


async def test_an_unfixable_lesson_lists_the_broken_rules_and_prints_nothing_of_it(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts.llm_smoke import run_lesson

    code = await run_lesson(
        FakeProvider(script=[{"title": "nonsense"}, {"title": "still nonsense"}]), show=True
    )

    report = capsys.readouterr().out
    assert code == 1
    assert "broke" in report and "SCHEMA" in report
    assert "nonsense" not in report  # the model's answer is never echoed


def test_the_example_topic_is_a_lessonable_topic() -> None:
    from scripts.llm_smoke import example_topic

    topic = example_topic()

    assert topic.kind == "topic" and topic.language == "en"
    assert topic.earlier_titles and topic.later_titles


# --- The quiz check --------------------------------------------------------------------------


async def test_a_working_provider_gets_a_clear_quiz_report_with_the_marking(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from app.ai.factory import builtin_responder
    from scripts.llm_smoke import run_quiz

    code = await run_quiz(FakeProvider(builtin_responder))

    report = capsys.readouterr().out
    assert code == 0
    assert "produced a valid quiz" in report and "synthetic:    yes" in report
    assert "questions:    5 (3 multiple choice, 1 true/false, 1 short answer)" in report
    assert "rubric points met for a partial answer" in report
    assert "call lesson.write" not in report  # the lesson is a built-in sample unless asked for
    assert "call quiz.write: finish=STOP" in report
    assert "call grade.short_answer: finish=STOP" in report
    assert "why:" not in report  # the quiz itself, with its answers, is only printed on request


async def test_the_quiz_and_its_answers_are_printed_on_request(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from app.ai.factory import builtin_responder
    from scripts.llm_smoke import run_quiz

    code = await run_quiz(FakeProvider(builtin_responder), show=True)

    report = capsys.readouterr().out
    assert code == 0
    assert "model answer:" in report and "rubric p1" in report and "why:" in report
    assert "   * " in report  # the right option of each choice question is marked


async def test_a_quiz_provider_error_is_reported_with_its_code(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts.llm_smoke import run_quiz

    code = await run_quiz(FakeProvider(script=[LLMRateLimited("HTTP 429: quota")]))

    report = capsys.readouterr().out
    assert code == 1
    assert "FAILED: AI_RATE_LIMITED (retryable: True)" in report


async def test_a_live_lesson_can_be_asked_for_and_is_then_one_more_call(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from app.ai.factory import builtin_responder
    from scripts.llm_smoke import run_quiz

    code = await run_quiz(FakeProvider(builtin_responder), live_lesson=True)

    report = capsys.readouterr().out
    assert code == 0
    assert "call lesson.write: finish=STOP" in report and "call quiz.write: finish=STOP" in report
