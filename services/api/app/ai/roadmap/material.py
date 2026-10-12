"""The learner's own documents as the planner sees them: a short contents list per document.

A roadmap built only from a goal's title cannot follow the learner's textbook or notes. When the
goal has ready documents, the worker reads which section each stored passage belongs to (no model
call, no embedding) and this module turns that into a contents list: ``S1`` for a document, ``C3``
for a section, with the pages it covers. The planner is told to build the plan from that list and to
name the sections it used; ``ground_evidence`` then swaps the short labels for the real document and
passage ids before anything is stored, the same way lessons do (``app.ai.lesson.grounding``).

Section titles are headings the chunker detected automatically, so a few are stray labels (a
caption, a diagram's text). Ones with no real word in them are folded into the section before; the
model is told the rest may contain noise. The titles are the learner's content, so they are data
inside the fence like everything else.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any

from app.ai.roadmap.schema import PlanEvidence, PlannedRoadmap

MAX_DOCUMENTS = 5
# The contents list is part of every planning prompt; this keeps it to a couple of screens.
MAX_SECTIONS = 70
_MAX_TITLE_CHARS = 90
_WORD_RE = re.compile(r"[^\W\d_]{3,}")


@dataclass(frozen=True)
class ChunkRef:
    """One stored passage's place in its document (no text)."""

    document_id: str
    document_title: str
    paginated: bool
    page_count: int | None
    chunk_id: str
    page_start: int
    page_end: int
    section_title: str | None


@dataclass(frozen=True)
class MaterialSection:
    label: str
    title: str
    first_page: int
    last_page: int
    # The first passage of the section: what a stored plan points at.
    chunk_id: str
    passages: int

    def position(self, *, paginated: bool) -> str:
        unit = "page" if paginated else "part"
        if self.first_page == self.last_page:
            return f"{unit} {self.first_page}"
        return f"{unit}s {self.first_page}-{self.last_page}"


@dataclass(frozen=True)
class MaterialDocument:
    label: str
    document_id: str
    title: str
    paginated: bool
    page_count: int | None
    sections: tuple[MaterialSection, ...]

    def as_data(self) -> dict[str, Any]:
        return {
            "source": self.label,
            "title": self.title,
            "pages": self.page_count if self.paginated else None,
            "contents": [
                {
                    "id": section.label,
                    "title": section.title,
                    "where": section.position(paginated=self.paginated),
                }
                for section in self.sections
            ],
        }

    def last_page(self) -> int:
        """The highest page (or part) number that really exists in this document."""
        known = max((section.last_page for section in self.sections), default=0)
        return max(known, self.page_count or 0)


def _heading(title: str | None) -> str | None:
    """A usable section title, or None when the line is not a heading in any useful sense."""
    if title is None:
        return None
    cleaned = " ".join(title.split())
    if not _WORD_RE.search(cleaned):
        return None
    return cleaned[:_MAX_TITLE_CHARS].rstrip()


def build_material(chunks: Sequence[ChunkRef]) -> tuple[MaterialDocument, ...]:
    """Group passages (ordered by document, then by position) into documents and sections."""
    grouped: dict[str, list[ChunkRef]] = {}
    for chunk in chunks:
        grouped.setdefault(chunk.document_id, []).append(chunk)

    documents: list[MaterialDocument] = []
    for index, (document_id, refs) in enumerate(grouped.items()):
        if index >= MAX_DOCUMENTS:
            break
        first = refs[0]
        sections = _sections_of(refs)
        if sections:
            documents.append(
                MaterialDocument(
                    label=f"S{len(documents) + 1}",
                    document_id=document_id,
                    title=first.document_title,
                    paginated=first.paginated,
                    page_count=first.page_count,
                    sections=tuple(sections),
                )
            )
    return _label_and_trim(documents)


def _sections_of(refs: Sequence[ChunkRef]) -> list[MaterialSection]:
    sections: list[MaterialSection] = []
    current_title: str | None = None
    for ref in refs:
        title = _heading(ref.section_title)
        if sections and (title is None or title == current_title):
            last = sections[-1]
            sections[-1] = replace(
                last,
                last_page=max(last.last_page, ref.page_end),
                passages=last.passages + 1,
            )
            continue
        current_title = title
        sections.append(
            MaterialSection(
                label="",
                title=title or "Opening part",
                first_page=ref.page_start,
                last_page=ref.page_end,
                chunk_id=ref.chunk_id,
                passages=1,
            )
        )
    return sections


def _label_and_trim(documents: list[MaterialDocument]) -> tuple[MaterialDocument, ...]:
    """Merge the smallest sections into the one before them until the list fits, then label."""
    lists = [list(document.sections) for document in documents]
    while sum(len(sections) for sections in lists) > MAX_SECTIONS:
        smallest: tuple[int, int] | None = None
        for d, sections in enumerate(lists):
            for s in range(1, len(sections)):
                if (
                    smallest is None
                    or sections[s].passages <= lists[smallest[0]][smallest[1]].passages
                ):
                    smallest = (d, s)
        if smallest is None:  # every document is down to one section
            break
        d, s = smallest
        previous = lists[d][s - 1]
        dropped = lists[d].pop(s)
        lists[d][s - 1] = replace(
            previous,
            last_page=max(previous.last_page, dropped.last_page),
            passages=previous.passages + dropped.passages,
        )
    labelled: list[MaterialDocument] = []
    number = 0
    for document, sections in zip(documents, lists, strict=True):
        numbered: list[MaterialSection] = []
        for section in sections:
            number += 1
            numbered.append(replace(section, label=f"C{number}"))
        labelled.append(replace(document, sections=tuple(numbered)))
    return tuple(labelled)


def evidence_labels(material: Sequence[MaterialDocument]) -> frozenset[tuple[str, str]]:
    """The (document, section) label pairs a plan may name as its evidence."""
    return frozenset(
        (document.label, section.label) for document in material for section in document.sections
    )


def highest_page(material: Sequence[MaterialDocument]) -> int:
    return max((document.last_page() for document in material), default=0)


def ground_evidence(plan: PlannedRoadmap, material: Sequence[MaterialDocument]) -> PlannedRoadmap:
    """Replace the plan's ``S1``/``C3`` labels with the real document and passage ids.

    Labels outside the contents list were already rejected by validation; any that remain are
    dropped rather than guessed. The same section named twice is kept once.
    """
    real: dict[tuple[str, str], PlanEvidence] = {}
    for document in material:
        for section in document.sections:
            real[(document.label, section.label)] = PlanEvidence(
                source_id=document.document_id, chunk_id=section.chunk_id
            )
    seen: set[tuple[str, str]] = set()
    grounded: list[PlanEvidence] = []
    for reference in plan.evidence:
        found = real.get((reference.source_id, reference.chunk_id))
        if found is None:
            continue
        key = (found.source_id, found.chunk_id)
        if key not in seen:
            seen.add(key)
            grounded.append(found)
    return plan.model_copy(update={"evidence": grounded})
