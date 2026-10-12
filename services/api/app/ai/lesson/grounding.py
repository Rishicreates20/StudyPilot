"""Turning the model's source labels into real citations, and deciding how grounded a lesson is.

The model cites passages by the short labels it was given ("S1" / "P2"). Validation has already
rejected any label that was not supplied. Here code replaces each label pair with the real document
id and passage id of the retrieved passage, drops anything unknown, and records whether the lesson
rests on the learner's material. The model never writes, and is never trusted about, an identifier,
a page number or whether its lesson is grounded.
"""

from collections.abc import Sequence

from app.ai.lesson.context import EvidenceChunk
from app.ai.lesson.schema import Lesson


def ground_lesson(
    lesson: Lesson, evidence: Sequence[EvidenceChunk], *, has_documents: bool
) -> Lesson:
    """``lesson`` with real citations and its ``grounding`` set by what actually happened."""
    by_label = {(chunk.source_id, chunk.chunk_id): chunk for chunk in evidence}
    seen: set[str] = set()
    references: list[dict[str, str | None]] = []
    for reference in lesson.source_references:
        chunk = by_label.get((reference.source_id, reference.chunk_id))
        if chunk is None or not chunk.real_chunk_id or chunk.real_chunk_id in seen:
            continue
        seen.add(chunk.real_chunk_id)
        references.append(
            {
                "source_id": chunk.document_id,
                "chunk_id": chunk.real_chunk_id,
                "note": reference.note,
            }
        )
    if references:
        grounding = "sources"
    elif has_documents or evidence:
        grounding = "no_match"
    else:
        grounding = "none"
    document = lesson.model_dump(mode="json")
    document["source_references"] = references
    document["grounding"] = grounding
    return Lesson.model_validate(document)
