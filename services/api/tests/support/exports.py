"""Sources for export tests: lessons (English, Hindi, Odia) and a roadmap, without a database."""

import uuid
from datetime import UTC, date, datetime
from typing import Any

from app.ai.lesson.schema import Lesson
from app.exports.model import LessonSource, RoadmapSource
from app.schemas.lessons import Citation, ItemStudy, LessonDetail
from app.schemas.roadmaps import Objective, Roadmap, RoadmapItem, RoadmapModule
from support.lessons import valid_lesson

HINDI_TITLE = "स्वामित्व और उधार"  # स्वामित्व और उधार
HINDI_TEXT = (
    "रस्ट में हर मान का "
    "एक ही स्वामी होता "
    "है। क्षत्रिय शिक्"
    "षा का उदाहरण।"
)  # रस्ट में हर मान का एक ही स्वामी होता है। क्षत्रिय शिक्षा का उदाहरण।
ODIA_TEXT = "ଓଡ଼ିଆ ଶିକ୍ଷା: ପ୍ରତ୍ୟେକ ମୂଲ୍ୟର ଏକ ମାଲିକ ଅଛନ୍ତି।"  # ଓଡ଼ିଆ ଶିକ୍ଷା: ପ୍ରତ୍ୟେକ ମୂଲ୍ୟର ଏକ ମାଲିକ ଅଛନ୍ତି।

CREATED = datetime(2026, 10, 12, 9, 30, tzinfo=UTC)


def lesson_detail(
    content: Lesson | None = None,
    *,
    language: str = "en",
    is_synthetic: bool = False,
    citations: list[Citation] | None = None,
) -> LessonDetail:
    content = content or valid_lesson()
    return LessonDetail(
        id=uuid.uuid4(),
        version=2,
        status="current",
        title=content.title,
        adjust=None,
        is_synthetic=is_synthetic,
        created_at=CREATED,
        item_id=uuid.uuid4(),
        language=language,
        content=content,
        content_version=1,
        revision_feedback=None,
        based_on_lesson_id=None,
        prompt_version="lesson-writer/v2",
        provider="gemini",
        model_id="gemini-test",
        citations=citations or [],
    )


def lesson_source(**options: Any) -> LessonSource:
    return LessonSource(
        lesson=lesson_detail(**options),
        topic_title="Ownership and borrowing",
        goal_title="Learn the Rust programming language",
    )


def indic_lesson() -> Lesson:
    """The sample lesson with Hindi and Odia text in its title, prose, terms and summary."""
    data = valid_lesson().model_dump()
    data["language"] = "hi"
    data["title"] = HINDI_TITLE
    data["learning_objectives"][0] = HINDI_TEXT
    data["sections"][0]["heading"] = HINDI_TITLE
    data["sections"][0]["blocks"].insert(0, {"type": "paragraph", "text": HINDI_TEXT})
    data["sections"][0]["blocks"].insert(1, {"type": "paragraph", "text": ODIA_TEXT})
    data["summary"][0] = HINDI_TEXT
    data["summary"][1] = ODIA_TEXT
    data["definitions"].append({"term": HINDI_TITLE, "meaning": HINDI_TEXT})
    return Lesson.model_validate(data)


def cited_sources() -> list[Citation]:
    return [
        Citation(
            source_id="S1",
            chunk_id=str(uuid.uuid4()),
            note="Defines ownership",
            available=True,
            document_id=uuid.uuid4(),
            document_title="Rust lecture notes",
            position="pp. 3 to 4",
            page_start=3,
        ),
        Citation(source_id="S2", chunk_id=str(uuid.uuid4()), note=None, available=False),
    ]


def _item(kind: str, position: int, title: str, day: int | None, **extra: Any) -> RoadmapItem:
    return RoadmapItem(
        id=uuid.uuid4(),
        kind=kind,  # type: ignore[arg-type]
        position=position,
        key=f"item-{position}",
        title=title,
        description=f"What {title} covers, and why it matters at this point in the plan.",
        practice_task=extra.get("practice_task"),
        objective_ids=extra.get("objective_ids", ["o1"]),
        estimated_minutes=extra.get("minutes", 45),
        day_number=day,
        prerequisite_ids=[],
        study=ItemStudy(status="not_started", has_lesson=False, sections_done=0, sections_total=0),
    )


def roadmap_source(*, is_synthetic: bool = False, topics: int = 9) -> RoadmapSource:
    module_size = 3
    modules: list[RoadmapModule] = []
    position = 1
    for number in range(1, (topics + module_size - 1) // module_size + 1):
        items: list[RoadmapItem] = []
        for _ in range(module_size):
            if position > topics:
                break
            items.append(
                _item(
                    "topic",
                    position,
                    f"Topic {position}: memory, borrowing and lifetimes",
                    position,
                    practice_task="Write a short program that uses this idea.",
                    objective_ids=["o1", "o2"],
                )
            )
            position += 1
        modules.append(
            RoadmapModule(
                id=uuid.uuid4(),
                position=number,
                title=f"Module {number} title",
                summary="What this module covers and how it builds on the previous one.",
                topics=items,
            )
        )
    revision = _item("revision", position, "Review the first week", topics + 1, minutes=30)
    extra = _item("enrichment", position + 1, "Read the Rustonomicon", None, minutes=60)
    return RoadmapSource(
        roadmap=Roadmap(
            id=uuid.uuid4(),
            goal_id=uuid.uuid4(),
            version=1,
            status="current",
            title="Rust in four weeks",
            language="en",
            topic_count=topics,
            total_minutes=45 * topics + 30,
            total_days=topics + 1,
            daily_minutes=45,
            target_date=date(2026, 12, 1),
            revision_feedback=None,
            based_on_roadmap_id=None,
            is_synthetic=is_synthetic,
            completed_topics=0,
            created_at=CREATED,
            overview=(
                "A steady plan from the basics of ownership to writing small programs. "
                "Each week ends with revision. The pace assumes about 45 minutes a day."
            ),
            target_outcome="Write and explain small Rust programs that compile first time.",
            syllabus_basis="general_knowledge",
            assumptions=["You can already program in another language."],
            unknowns=["Whether your course expects async Rust."],
            objectives=[
                Objective(id="o1", text="Explain ownership and borrowing"),
                Objective(id="o2", text="Write programs that use them correctly"),
            ],
            prompt_version="roadmap-planner/v2",
            modules=modules,
            revision_sessions=[revision],
            enrichment=[extra],
        ),
        goal_title="Learn the Rust programming language",
    )
