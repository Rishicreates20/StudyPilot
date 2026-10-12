"""The facts a lesson is written from: one topic, the learner, and what they already covered.

Built once per job and used twice: rendered into the prompt, and handed to the validator, so the
rules the lesson is checked against are the same facts the model was given.
"""

import re
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from app.ai.lesson.schema import Adjust, Lesson
from app.schemas.goals import Goal

_PAGE_RANGE = r"\d{1,5}(?:\s*(?:-|\u2013|\u2014|to)\s*\d{1,5})?"
_PAGE_LIST = rf"\b(?:pages?|pp?\.)\s*{_PAGE_RANGE}(?:\s*(?:,|and|&)\s*{_PAGE_RANGE})*"
# "(Pages 42-48, 58-65)" at the end of a topic title: the whole bracket goes.
_BRACKETED_PAGES_RE = re.compile(rf"\s*[(\[][^()\[\]]*?{_PAGE_LIST}[^()\[\]]*?[)\]]", re.IGNORECASE)
_PAGES_RE = re.compile(_PAGE_LIST, re.IGNORECASE)


def without_page_references(text: str) -> str:
    """``text`` with page numbers taken out: "Keys (Pages 3-9)" -> "Keys".

    A plan built from a learner's document names the pages a topic covers, and that is useful on the
    roadmap. The lesson writer is never given page numbers (the app shows where each cited passage
    came from), and a lesson that repeats one from its topic's title would be rejected and cost a
    repair call. So the writer, and the search for the topic's passages, see the topic without them.
    """
    text = _BRACKETED_PAGES_RE.sub("", text)
    text = _PAGES_RE.sub("the relevant pages", text)
    return " ".join(text.split())


# Roughly how many words of lesson text suit a topic: enough to teach it, not a chapter. Reading and
# understanding take time, and the rest of the topic's minutes go to the practice task.
WORDS_PER_PLANNED_MINUTE = 35
MIN_TARGET_WORDS = 300
MAX_TARGET_WORDS = 1500
# Software accepts up to this much over the target before asking for a shorter lesson.
OVERRUN_FACTOR = 2.0
# Anything thinner than this cannot teach a topic, whatever the topic.
MIN_LESSON_WORDS = 120

_MAX_COVERED = 15
_MAX_NEXT = 3


@dataclass(frozen=True)
class EvidenceChunk:
    """A passage of the learner's own uploaded material the lesson may rely on and cite.

    ``source_id`` and ``chunk_id`` are short labels ("S1", "P2") that the model sees and cites: a
    model copies a two-character label reliably and a 36-character identifier unreliably. The real
    document and passage ids stay on the software side, and ``ground_lesson`` swaps them in before
    anything is stored, so a stored citation always points at a passage that was really retrieved.
    """

    source_id: str
    chunk_id: str
    title: str
    text: str
    # The real identifiers and position of the retrieved passage (never shown to the model).
    document_id: str = ""
    real_chunk_id: str = ""
    position: str = ""


@dataclass(frozen=True)
class TopicFacts:
    """What the roadmap says about one topic, read from the database for the lesson job."""

    item_id: UUID
    roadmap_id: UUID
    roadmap_status: str
    kind: str
    title: str
    description: str
    practice_task: str | None
    estimated_minutes: int
    module_title: str | None
    module_summary: str | None
    # The text of the roadmap objectives this topic serves.
    objectives: tuple[str, ...]
    language: str
    syllabus_basis: str
    # Titles of the topics before and after this one in the roadmap's study order.
    earlier_titles: tuple[str, ...]
    later_titles: tuple[str, ...]


@dataclass(frozen=True)
class LessonContext:
    goal_title: str
    goal_type: str
    level: str
    # The language the lesson is written in: the language of the roadmap it belongs to.
    language: str
    learning_preferences: tuple[str, ...]
    topic_title: str
    topic_description: str
    practice_task: str | None
    estimated_minutes: int
    module_title: str | None
    module_summary: str | None
    # The text of the roadmap objectives this topic serves.
    objectives: tuple[str, ...]
    # Titles of topics that come earlier in the roadmap: what the learner is assumed to have met.
    already_covered: tuple[str, ...]
    # Titles of the next few topics, so the lesson does not teach what they will.
    coming_next: tuple[str, ...]
    syllabus_basis: str
    # Passages of the learner's own material that may be cited: the ones retrieved for this topic.
    evidence: tuple[EvidenceChunk, ...] = ()
    # Whether the learner has any ready documents for the goal (even if none matched this topic).
    has_documents: bool = False
    adjust: Adjust | None = None
    feedback: str | None = None
    # The lesson being changed, when ``adjust`` or ``feedback`` asks for a different version.
    previous_lesson: Lesson | None = None
    extra: dict[str, Any] = field(default_factory=lambda: {})

    @property
    def evidence_ids(self) -> frozenset[tuple[str, str]]:
        return frozenset((chunk.source_id, chunk.chunk_id) for chunk in self.evidence)

    @property
    def target_words(self) -> int:
        planned = self.estimated_minutes * WORDS_PER_PLANNED_MINUTE
        return max(MIN_TARGET_WORDS, min(MAX_TARGET_WORDS, planned))

    @property
    def max_words(self) -> int:
        return int(self.target_words * OVERRUN_FACTOR)

    def input_data(self) -> dict[str, Any]:
        """The facts as plain data: rendered into the prompt, and used by the test double."""
        return {
            "goal": {"title": self.goal_title, "type": self.goal_type, "level": self.level},
            "language": self.language,
            "learning_preferences": list(self.learning_preferences),
            "topic": {
                "title": self.topic_title,
                "description": self.topic_description,
                "practice_task": self.practice_task,
                "planned_minutes": self.estimated_minutes,
                "module": self.module_title,
                "module_summary": self.module_summary,
                "objectives": list(self.objectives),
            },
            "already_covered": list(self.already_covered[-_MAX_COVERED:]),
            "coming_next": list(self.coming_next[:_MAX_NEXT]),
            "syllabus_basis": self.syllabus_basis,
            "length": {"target_words": self.target_words, "max_words": self.max_words},
            "source_material": [
                {
                    "source_id": chunk.source_id,
                    "chunk_id": chunk.chunk_id,
                    "title": chunk.title,
                    "text": chunk.text,
                }
                for chunk in self.evidence
            ],
            "has_source_material": bool(self.evidence),
            # True when the learner uploaded material but nothing in it matched this topic: the
            # lesson then relies on general knowledge and must not pretend otherwise.
            "material_did_not_cover_topic": self.has_documents and not self.evidence,
            "change_request": (
                {"adjust": self.adjust, "feedback": self.feedback}
                if self.adjust or self.feedback
                else None
            ),
            "previous_lesson": (
                self.previous_lesson.model_dump(mode="json") if self.previous_lesson else None
            ),
        }


def build_context(
    goal: Goal,
    facts: TopicFacts,
    *,
    adjust: Adjust | None = None,
    feedback: str | None = None,
    previous_lesson: Lesson | None = None,
    evidence: tuple[EvidenceChunk, ...] = (),
    has_documents: bool = False,
) -> LessonContext:
    return LessonContext(
        goal_title=goal.title,
        goal_type=goal.goal_type,
        level=goal.current_level,
        language=facts.language,
        learning_preferences=tuple(goal.learning_preferences),
        topic_title=without_page_references(facts.title),
        topic_description=without_page_references(facts.description),
        practice_task=(
            without_page_references(facts.practice_task) if facts.practice_task else None
        ),
        estimated_minutes=facts.estimated_minutes,
        module_title=without_page_references(facts.module_title) if facts.module_title else None,
        module_summary=(
            without_page_references(facts.module_summary) if facts.module_summary else None
        ),
        objectives=tuple(without_page_references(text) for text in facts.objectives),
        already_covered=tuple(without_page_references(t) for t in facts.earlier_titles),
        coming_next=tuple(without_page_references(t) for t in facts.later_titles),
        syllabus_basis=facts.syllabus_basis,
        evidence=evidence,
        has_documents=has_documents or bool(evidence),
        adjust=adjust,
        feedback=feedback,
        previous_lesson=previous_lesson,
    )
