"""Checks a generated roadmap against the learner's real constraints, in code.

A model's answer can be perfectly well-formed and still be wrong for this learner: too many
minutes in a day, a topic that needs one that comes later, an objective nothing teaches. These
checks catch that deterministically. Nothing here asks a model whether its own plan is good.

``validate_plan`` returns *every* problem it finds, worded as instructions, so the planner can
hand the whole list back for one repair attempt.
"""

import re
from collections import Counter, defaultdict
from dataclasses import dataclass

from app.ai.roadmap.context import PlanningContext
from app.ai.roadmap.schema import MAX_TOPICS, PlannedRoadmap, PlanRevision, PlanTopic

_KEY_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_MAX_REPORTED = 25
_MAX_DAYS_LISTED = 6
_EXAM_LIKE = frozenset({"exam", "certification"})


@dataclass(frozen=True)
class Violation:
    code: str
    message: str


@dataclass(frozen=True)
class PlanMetrics:
    topic_count: int
    # Minutes of core study and revision. Optional enrichment is not part of the time plan.
    total_minutes: int
    # The last day with anything scheduled.
    total_days: int


def normalize_key(value: str) -> str:
    """``"Pointers & Memory"`` -> ``"pointers-memory"``. Applied to keys and to every reference."""
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def normalize_plan(plan: PlannedRoadmap) -> PlannedRoadmap:
    """Fix harmless formatting differences in identifiers, consistently everywhere they appear."""
    data = plan.model_dump()
    for objective in data["objectives"]:
        objective["id"] = normalize_key(objective["id"])
    for module in data["modules"]:
        for topic in module["topics"]:
            topic["key"] = normalize_key(topic["key"])
            topic["objective_ids"] = [normalize_key(o) for o in topic["objective_ids"]]
            topic["prerequisite_keys"] = [normalize_key(k) for k in topic["prerequisite_keys"]]
    for revision in data["revision_sessions"]:
        revision["key"] = normalize_key(revision["key"])
        revision["revisits"] = [normalize_key(k) for k in revision["revisits"]]
    for extra in data["enrichment"]:
        extra["key"] = normalize_key(extra["key"])
    data["language"] = data["language"].strip().lower()
    return PlannedRoadmap.model_validate(data)


def measure(plan: PlannedRoadmap) -> PlanMetrics:
    """Totals computed by code. The model is never asked for them, so it cannot misstate them."""
    topics = plan.topics()
    scheduled = [*(t.day for t in topics), *(r.day for r in plan.revision_sessions)]
    minutes = sum(t.estimated_minutes for t in topics) + sum(
        r.estimated_minutes for r in plan.revision_sessions
    )
    return PlanMetrics(
        topic_count=len(topics),
        total_minutes=minutes,
        total_days=max(scheduled) if scheduled else 0,
    )


def validate_plan(plan: PlannedRoadmap, context: PlanningContext) -> list[Violation]:
    """Every rule the plan breaks, or an empty list when it is acceptable."""
    found: list[Violation] = []
    topics = plan.topics()

    _check_language(plan, context, found)
    _check_keys(plan, topics, found)
    _check_objectives(plan, topics, found)
    _check_order_and_prerequisites(topics, found)
    _check_daily_budget(plan, topics, context, found)
    _check_horizon(plan, topics, context, found)
    _check_revision(plan.revision_sessions, topics, found)
    _check_evidence_and_unknowns(plan, context, found)

    return found[:_MAX_REPORTED]


def _add(found: list[Violation], code: str, message: str) -> None:
    found.append(Violation(code, message))


def _check_language(plan: PlannedRoadmap, context: PlanningContext, found: list[Violation]) -> None:
    if plan.language not in context.languages:
        _add(
            found,
            "LANGUAGE",
            f'The plan is written in "{plan.language}", but the learner chose '
            f"{', '.join(context.languages)}. Write it in {context.languages[0]}.",
        )


def _check_keys(plan: PlannedRoadmap, topics: list[PlanTopic], found: list[Violation]) -> None:
    if len(topics) > MAX_TOPICS:
        _add(
            found,
            "TOO_MANY_TOPICS",
            f"The plan has {len(topics)} topics; use at most {MAX_TOPICS}.",
        )
    keyed = [
        *((t.key, "topic") for t in topics),
        *((r.key, "revision session") for r in plan.revision_sessions),
        *((e.key, "enrichment topic") for e in plan.enrichment),
    ]
    for key, kind in keyed:
        if not _KEY_RE.match(key):
            _add(
                found,
                "KEY_FORMAT",
                f'The {kind} key "{key}" must use only lowercase letters, digits and '
                "single hyphens.",
            )
    for key, count in Counter(key for key, _ in keyed).items():
        if count > 1:
            _add(
                found,
                "KEY_DUPLICATE",
                f'The key "{key}" is used {count} times; keys must be unique.',
            )


def _check_objectives(
    plan: PlannedRoadmap, topics: list[PlanTopic], found: list[Violation]
) -> None:
    ids = [objective.id for objective in plan.objectives]
    for objective_id, count in Counter(ids).items():
        if count > 1:
            _add(
                found,
                "OBJECTIVE_DUPLICATE",
                f'The objective id "{objective_id}" is used {count} times.',
            )
    known = set(ids)
    for topic in topics:
        unknown = [oid for oid in topic.objective_ids if oid not in known]
        if unknown:
            _add(
                found,
                "OBJECTIVE_UNKNOWN",
                f'Topic "{topic.key}" refers to objective(s) {", ".join(unknown)} that are not '
                "listed under objectives.",
            )
    covered = {oid for topic in topics for oid in topic.objective_ids}
    uncovered = [oid for oid in ids if oid not in covered]
    if uncovered:
        _add(
            found,
            "OBJECTIVE_UNCOVERED",
            f"No topic covers objective(s) {', '.join(uncovered)}. Add a topic for each, or "
            "remove the objective.",
        )


def _check_order_and_prerequisites(topics: list[PlanTopic], found: list[Violation]) -> None:
    position = {topic.key: index for index, topic in enumerate(topics)}
    by_key = {topic.key: topic for topic in topics}
    for index, topic in enumerate(topics):
        if index and topic.day < topics[index - 1].day:
            _add(
                found,
                "DAY_ORDER",
                f'Topic "{topic.key}" is on day {topic.day}, before the previous topic '
                f"(day {topics[index - 1].day}). Days must not go backwards.",
            )
        for prerequisite in topic.prerequisite_keys:
            if prerequisite == topic.key:
                _add(
                    found,
                    "PREREQUISITE_SELF",
                    f'Topic "{topic.key}" lists itself as a prerequisite.',
                )
            elif prerequisite not in position:
                _add(
                    found,
                    "PREREQUISITE_UNKNOWN",
                    f'Topic "{topic.key}" needs "{prerequisite}", which is not a topic in '
                    "the plan.",
                )
            elif position[prerequisite] > index:
                _add(
                    found,
                    "PREREQUISITE_ORDER",
                    f'Topic "{topic.key}" needs "{prerequisite}", which comes later. '
                    "Put prerequisites first.",
                )
            elif by_key[prerequisite].day > topic.day:
                _add(
                    found,
                    "PREREQUISITE_SCHEDULE",
                    f'Topic "{topic.key}" (day {topic.day}) is scheduled before its '
                    f'prerequisite "{prerequisite}" (day {by_key[prerequisite].day}).',
                )


def _check_daily_budget(
    plan: PlannedRoadmap,
    topics: list[PlanTopic],
    context: PlanningContext,
    found: list[Violation],
) -> None:
    per_day: dict[int, int] = defaultdict(int)
    for topic in topics:
        per_day[topic.day] += topic.estimated_minutes
    for revision in plan.revision_sessions:
        per_day[revision.day] += revision.estimated_minutes
    over = sorted(day for day, minutes in per_day.items() if minutes > context.daily_minutes)
    for day in over[:_MAX_DAYS_LISTED]:
        _add(
            found,
            "DAILY_BUDGET",
            f"Day {day} has {per_day[day]} minutes planned, but the learner has only "
            f"{context.daily_minutes} minutes a day. Move work to another day or shorten it.",
        )
    if len(over) > _MAX_DAYS_LISTED:
        _add(
            found,
            "DAILY_BUDGET",
            f"{len(over) - _MAX_DAYS_LISTED} more days also exceed "
            f"{context.daily_minutes} minutes.",
        )


def _check_horizon(
    plan: PlannedRoadmap,
    topics: list[PlanTopic],
    context: PlanningContext,
    found: list[Violation],
) -> None:
    scheduled = [*(t.day for t in topics), *(r.day for r in plan.revision_sessions)]
    last_day = max(scheduled) if scheduled else 0
    if last_day > context.max_days:
        reason = (
            f"the target date ({context.target_date}) leaves {context.max_days} days"
            if context.target_date
            else f"plans may run at most {context.max_days} days"
        )
        _add(
            found,
            "HORIZON",
            f"The plan runs to day {last_day}, but {reason}. Fit everything within "
            f"{context.max_days} days (day 1 is today), cutting or merging topics if needed.",
        )


def _check_revision(
    sessions: list[PlanRevision], topics: list[PlanTopic], found: list[Violation]
) -> None:
    day_of = {topic.key: topic.day for topic in topics}
    for session in sessions:
        unknown = [key for key in session.revisits if key not in day_of]
        if unknown:
            _add(
                found,
                "REVISION_UNKNOWN",
                f'Revision session "{session.key}" revisits {", ".join(unknown)}, which are '
                "not topics.",
            )
        known_days = [day_of[key] for key in session.revisits if key in day_of]
        if known_days and session.day < max(known_days):
            _add(
                found,
                "REVISION_ORDER",
                f'Revision session "{session.key}" (day {session.day}) comes before a topic it '
                f"revisits (day {max(known_days)}).",
            )


def _check_evidence_and_unknowns(
    plan: PlannedRoadmap, context: PlanningContext, found: list[Violation]
) -> None:
    for reference in plan.evidence:
        if (reference.source_id, reference.chunk_id) not in context.evidence_ids:
            _add(
                found,
                "EVIDENCE_UNKNOWN",
                "The plan cites material that was not provided. Remove all evidence references "
                "that are not in the supplied material.",
            )
            break
    if plan.syllabus_basis == "uploaded_document" and not context.evidence_ids:
        _add(
            found,
            "BASIS_NO_MATERIAL",
            'syllabus_basis is "uploaded_document" but the learner uploaded nothing. Use '
            '"learner_stated" or "general_knowledge".',
        )
    if context.goal_type in _EXAM_LIKE and not context.evidence_ids and not plan.unknowns:
        _add(
            found,
            "UNKNOWNS_REQUIRED",
            "This is an exam or certification goal and no official syllabus was provided. List, "
            "under unknowns, what you could not verify (official syllabus, exam pattern, dates), "
            "and do not present the plan as the official one.",
        )
