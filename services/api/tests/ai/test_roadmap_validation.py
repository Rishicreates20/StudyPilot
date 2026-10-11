"""The programmatic checks on a generated roadmap: budgets, order, prerequisites, coverage."""

from collections.abc import Callable
from typing import Any

import pytest

from app.ai.roadmap.validation import measure, normalize_key, normalize_plan, validate_plan
from support.plans import changed, make_context, valid_plan


def codes(plan: Any, context: Any) -> set[str]:
    return {violation.code for violation in validate_plan(plan, context)}


# --- A good plan -----------------------------------------------------------------------------


def test_a_plan_that_follows_every_rule_has_no_violations() -> None:
    context = make_context()

    assert validate_plan(valid_plan(context), context) == []


@pytest.mark.parametrize("daily_minutes", [5, 10, 25, 240])
@pytest.mark.parametrize("max_days", [1, 2, 3, 10, 365])
def test_the_sample_plan_fits_any_schedule_it_is_given(daily_minutes: int, max_days: int) -> None:
    context = make_context(daily_minutes=daily_minutes, max_days=max_days)

    assert validate_plan(valid_plan(context), context) == []


def test_metrics_are_computed_by_code_from_the_plan() -> None:
    context = make_context(daily_minutes=60, max_days=30)
    plan = valid_plan(context)

    metrics = measure(plan)

    topic_minutes = sum(t.estimated_minutes for t in plan.topics())
    revision_minutes = sum(r.estimated_minutes for r in plan.revision_sessions)
    assert metrics.topic_count == len(plan.topics())
    assert metrics.total_minutes == topic_minutes + revision_minutes
    assert metrics.total_days == max(
        [*(t.day for t in plan.topics()), *(r.day for r in plan.revision_sessions)]
    )


def test_optional_enrichment_does_not_count_towards_the_time_plan() -> None:
    context = make_context()
    plan = valid_plan(context)
    assert plan.enrichment

    def make_extra_huge(data: dict[str, Any]) -> None:
        data["enrichment"][0]["estimated_minutes"] = 480

    with_big_extra = changed(plan, make_extra_huge)

    assert measure(with_big_extra) == measure(plan)
    assert validate_plan(with_big_extra, context) == []


# --- Time budget -----------------------------------------------------------------------------


def test_a_day_over_the_daily_minutes_is_rejected() -> None:
    context = make_context(daily_minutes=30)
    plan = valid_plan(make_context(daily_minutes=60))

    violations = validate_plan(plan, context)

    assert {v.code for v in violations} == {"DAILY_BUDGET"}
    assert "30 minutes a day" in violations[0].message


def test_revision_minutes_count_against_the_same_day() -> None:
    context = make_context(daily_minutes=60)
    plan = valid_plan(context)

    def put_revision_on_a_study_day(data: dict[str, Any]) -> None:
        data["revision_sessions"][0]["day"] = data["modules"][-1]["topics"][-1]["day"]
        data["revision_sessions"][0]["estimated_minutes"] = 45

    assert "DAILY_BUDGET" in codes(changed(plan, put_revision_on_a_study_day), context)


def test_a_plan_that_runs_past_the_target_date_is_rejected() -> None:
    plan = valid_plan(make_context(max_days=30))

    violations = validate_plan(plan, make_context(max_days=3, target_date=None))

    assert "HORIZON" in {v.code for v in violations}


def test_the_horizon_message_names_the_target_date() -> None:
    from datetime import date

    context = make_context(max_days=2, target_date=date(2026, 10, 13))

    violations = [
        v for v in validate_plan(valid_plan(make_context()), context) if v.code == "HORIZON"
    ]

    assert violations
    assert "2026-10-13" in violations[0].message


# --- Order and prerequisites -----------------------------------------------------------------


def edit_topic(index: int, **fields: Any) -> Callable[[dict[str, Any]], None]:
    def edit(data: dict[str, Any]) -> None:
        topics = [t for m in data["modules"] for t in m["topics"]]
        topics[index].update(fields)

    return edit


def test_days_may_not_go_backwards() -> None:
    context = make_context()
    plan = changed(valid_plan(context), edit_topic(2, day=1))

    assert "DAY_ORDER" in codes(plan, context)


def test_a_prerequisite_that_does_not_exist_is_rejected() -> None:
    context = make_context()
    plan = changed(valid_plan(context), edit_topic(1, prerequisite_keys=["nonexistent"]))

    assert "PREREQUISITE_UNKNOWN" in codes(plan, context)


def test_a_topic_cannot_be_its_own_prerequisite() -> None:
    context = make_context()
    plan = changed(valid_plan(context), edit_topic(1, prerequisite_keys=["part-2"]))

    assert "PREREQUISITE_SELF" in codes(plan, context)


def test_a_prerequisite_that_comes_later_is_rejected_so_cycles_are_impossible() -> None:
    context = make_context()
    plan = changed(valid_plan(context), edit_topic(0, prerequisite_keys=["part-2"]))

    assert "PREREQUISITE_ORDER" in codes(plan, context)


def test_a_topic_cannot_be_scheduled_before_its_prerequisite() -> None:
    context = make_context()
    # part-2 needs part-1, but part-1 is pushed to day 3 while part-2 stays on day 2.
    plan = changed(valid_plan(context), edit_topic(0, day=3))

    assert "PREREQUISITE_SCHEDULE" in codes(plan, context)


# --- Objectives ------------------------------------------------------------------------------


def test_an_objective_no_topic_teaches_is_rejected() -> None:
    context = make_context()

    def add_orphan_objective(data: dict[str, Any]) -> None:
        data["objectives"].append({"id": "o9", "text": "Something nothing teaches"})

    violations = validate_plan(changed(valid_plan(context), add_orphan_objective), context)

    assert [v.code for v in violations] == ["OBJECTIVE_UNCOVERED"]
    assert "o9" in violations[0].message


def test_a_topic_that_serves_an_unlisted_objective_is_rejected() -> None:
    context = make_context()
    plan = changed(valid_plan(context), edit_topic(0, objective_ids=["o77"]))

    assert "OBJECTIVE_UNKNOWN" in codes(plan, context)


def test_duplicate_objective_ids_are_rejected() -> None:
    context = make_context()

    def duplicate(data: dict[str, Any]) -> None:
        data["objectives"].append(dict(data["objectives"][0]))

    assert "OBJECTIVE_DUPLICATE" in codes(changed(valid_plan(context), duplicate), context)


# --- Keys ------------------------------------------------------------------------------------


def test_duplicate_keys_are_rejected_across_topics_and_revisions() -> None:
    context = make_context()
    plan = changed(valid_plan(context), edit_topic(1, key="part-1"))

    assert "KEY_DUPLICATE" in codes(plan, context)


def test_a_key_must_be_lowercase_words_joined_by_hyphens() -> None:
    context = make_context()
    plan = changed(valid_plan(context), edit_topic(0, key="Part One!"))

    assert "KEY_FORMAT" in codes(plan, context)


def test_normalization_repairs_formatting_everywhere_a_key_appears() -> None:
    context = make_context()

    def shout(data: dict[str, Any]) -> None:
        for module in data["modules"]:
            for topic in module["topics"]:
                topic["key"] = topic["key"].upper().replace("-", " ")
                topic["prerequisite_keys"] = [
                    k.upper().replace("-", " ") for k in topic["prerequisite_keys"]
                ]
        for revision in data["revision_sessions"]:
            revision["revisits"] = [k.upper().replace("-", " ") for k in revision["revisits"]]
        data["objectives"][0]["id"] = "O1"

    messy = changed(valid_plan(context), shout)
    assert codes(messy, context)  # not valid as the model wrote it

    assert validate_plan(normalize_plan(messy), context) == []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("Pointers & Memory", "pointers-memory"), ("  --A--B--  ", "a-b"), ("O1", "o1"), ("", "")],
)
def test_normalize_key(raw: str, expected: str) -> None:
    assert normalize_key(raw) == expected


# --- Revision sessions -----------------------------------------------------------------------


def test_a_revision_session_cannot_come_before_what_it_revisits() -> None:
    context = make_context()

    def too_early(data: dict[str, Any]) -> None:
        data["revision_sessions"][0]["day"] = 1

    assert "REVISION_ORDER" in codes(changed(valid_plan(context), too_early), context)


def test_a_revision_session_may_only_revisit_topics() -> None:
    context = make_context()

    def bad_target(data: dict[str, Any]) -> None:
        data["revision_sessions"][0]["revisits"] = ["explore-more"]

    assert "REVISION_UNKNOWN" in codes(changed(valid_plan(context), bad_target), context)


# --- Language, honesty and evidence ----------------------------------------------------------


def test_the_plan_must_be_in_one_of_the_learners_languages() -> None:
    context = make_context(languages=("en",))

    violations = validate_plan(valid_plan(make_context(languages=("hi",))), context)

    assert [v.code for v in violations] == ["LANGUAGE"]
    assert '"hi"' in violations[0].message


def test_an_exam_plan_without_an_official_syllabus_must_list_what_is_unknown() -> None:
    context = make_context(goal_type="exam")
    plan = changed(valid_plan(context), lambda d: d.update(unknowns=[]))

    violations = validate_plan(plan, context)

    assert [v.code for v in violations] == ["UNKNOWNS_REQUIRED"]
    assert "official" in violations[0].message


def test_a_non_exam_goal_may_have_no_unknowns() -> None:
    context = make_context(goal_type="professional_skill")
    plan = changed(valid_plan(context), lambda d: d.update(unknowns=[]))

    assert validate_plan(plan, context) == []


def test_claiming_an_uploaded_document_without_one_is_rejected() -> None:
    context = make_context()
    plan = changed(valid_plan(context), lambda d: d.update(syllabus_basis="uploaded_document"))

    assert "BASIS_NO_MATERIAL" in codes(plan, context)


def test_citing_material_that_was_never_provided_is_rejected() -> None:
    context = make_context()
    plan = changed(
        valid_plan(context),
        lambda d: d.update(evidence=[{"source_id": "doc-1", "chunk_id": "chunk-9"}]),
    )

    assert "EVIDENCE_UNKNOWN" in codes(plan, context)


def test_citing_provided_material_is_accepted() -> None:
    context = make_context(evidence_ids=frozenset({("doc-1", "chunk-9")}))
    plan = changed(
        valid_plan(context),
        lambda d: d.update(
            syllabus_basis="uploaded_document",
            evidence=[{"source_id": "doc-1", "chunk_id": "chunk-9"}],
        ),
    )

    assert validate_plan(plan, context) == []


def test_every_problem_is_reported_at_once_so_one_repair_can_fix_them_all() -> None:
    context = make_context(daily_minutes=20, goal_type="exam")

    def break_many(data: dict[str, Any]) -> None:
        data["unknowns"] = []
        data["objectives"].append({"id": "o9", "text": "Something nothing teaches"})
        data["modules"][0]["topics"][0]["prerequisite_keys"] = ["ghost"]

    plan = changed(valid_plan(make_context(daily_minutes=60, goal_type="exam")), break_many)

    assert codes(plan, context) >= {
        "DAILY_BUDGET",
        "UNKNOWNS_REQUIRED",
        "OBJECTIVE_UNCOVERED",
        "PREREQUISITE_UNKNOWN",
    }
