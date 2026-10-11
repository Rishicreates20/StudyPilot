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
