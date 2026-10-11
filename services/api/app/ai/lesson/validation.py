"""Turns a model's draft into the stored lesson document, and checks it in code.

A draft can be well-formed JSON and still be a bad lesson: a code block with no code, a section
with a heading and nothing under it, a link nobody can vouch for, a citation to material that was
never supplied. ``build_lesson`` and ``validate_lesson`` catch that deterministically, and report
*every* problem worded as an instruction, so the writer can hand the whole list back for one repair
attempt. Nothing here asks a model whether its own lesson is good.
"""

import re
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from app.ai.lesson.context import MIN_LESSON_WORDS, LessonContext
from app.ai.lesson.schema import (
    Block,
    CalloutBlock,
    CodeBlock,
    DraftBlock,
    DraftLesson,
    Lesson,
    LessonSection,
    ListBlock,
    ParagraphBlock,
)
from app.ai.violations import Violation

_MAX_REPORTED = 25
# Cosmetic fields are cut to these rather than sent back for repair (see ``build_lesson``).
_MAX_LANGUAGE_CHARS = 30
_MAX_CAPTION_CHARS = 200
_MAX_CALLOUT_TITLE_CHARS = 100
_MAX_NOTE_CHARS = 200
_MAX_ANALOGY_CHARS = 500
# A section needs a few sentences, not just a heading and a line.
_MIN_SECTION_WORDS = 15
_MIN_SIMPLE_CHARS = 80
_URL_RE = re.compile(r"(?:https?://|ftp://|www\.)\S+", re.IGNORECASE)
# A scholarly identifier in the prose is a claim about a real publication that nobody checked.
_PUBLICATION_RE = re.compile(r"\b(?:doi:\s*10\.|doi\.org/|isbn[\s:-]*\d)", re.IGNORECASE)
_LANGUAGE_CHARS_RE = re.compile(r"[^a-z0-9+#._-]")


def reading_units(text: str) -> int:
    """Words in ``text``; for scripts written without spaces, a character-based estimate."""
    words = len(text.split())
    if words * 12 < len(text):  # fewer than one space per 12 characters: not space-separated
        return len(text) // 2
    return words


@dataclass(frozen=True)
class LessonMetrics:
    sections: int
    words: int
    code_blocks: int
    examples: int


def _blocks(lesson: Lesson) -> Iterator[Block]:
    for section in lesson.sections:
        yield from section.blocks


def _section_prose(section: LessonSection) -> list[str]:
    """Everything a learner reads in a section except code."""
    parts: list[str] = []
    for block in section.blocks:
        if isinstance(block, ParagraphBlock | CalloutBlock):
            parts.append(block.text)
        elif isinstance(block, ListBlock):
            parts.extend(block.items)
    return parts


def prose_fragments(lesson: Lesson) -> Iterator[tuple[str, str]]:
    """``(where, text)`` for every piece of text a learner reads, code excluded."""
    yield "the title", lesson.title
    for text in lesson.learning_objectives:
        yield "a learning objective", text
    for section in lesson.sections:
        yield f'the section "{section.heading}"', section.heading
        for text in _section_prose(section):
            yield f'the section "{section.heading}"', text
        for block in section.blocks:
            if isinstance(block, CodeBlock) and block.caption:
                yield f'the section "{section.heading}"', block.caption
            if isinstance(block, CalloutBlock) and block.title:
                yield f'the section "{section.heading}"', block.title
    for definition in lesson.definitions:
        yield "a definition", f"{definition.term} {definition.meaning}"
    for example in lesson.worked_examples:
        yield (
            f'the example "{example.title}"',
            " ".join([example.problem, *example.steps, example.answer]),
        )
    for mistake in lesson.common_misconceptions:
        yield "a misconception", f"{mistake.misconception} {mistake.correction}"
    for text in lesson.summary:
        yield "the summary", text
    yield "the simple explanation", " ".join(lesson.simple_explanation.paragraphs)
    if lesson.simple_explanation.analogy:
        yield "the simple explanation", lesson.simple_explanation.analogy


def measure(lesson: Lesson) -> LessonMetrics:
    words = sum(reading_units(text) for _, text in prose_fragments(lesson))
    return LessonMetrics(
        sections=len(lesson.sections),
        words=words,
        code_blocks=sum(isinstance(block, CodeBlock) for block in _blocks(lesson)),
        examples=len(lesson.worked_examples),
    )


def _add(found: list[Violation], code: str, message: str) -> None:
    found.append(Violation(code, message))


def _or_none(text: str, limit: int | None = None) -> str | None:
    """``text`` stripped, cut to ``limit`` characters if given, or None when nothing is left."""
    text = text.strip()
    if limit is not None and len(text) > limit:
        text = text[: limit - 1].rstrip() + "\u2026"
    return text or None


def _convert_block(block: DraftBlock, where: str, found: list[Violation]) -> dict[str, Any] | None:
    """One block in the stored document's shape (a plain dict, validated with the whole lesson)."""
    if block.type == "paragraph":
        if not block.text.strip():
            _add(found, "EMPTY_BLOCK", f"{where} has a paragraph with no text.")
            return None
        return {"type": "paragraph", "text": block.text}
    if block.type == "list":
        items = [item.strip() for item in block.items if item.strip()]
        if not items:
            _add(found, "EMPTY_BLOCK", f"{where} has a list with no items.")
            return None
        return {"type": "list", "ordered": block.ordered, "items": items}
    if block.type == "code":
        if not block.code.strip():
            _add(found, "EMPTY_BLOCK", f"{where} has a code block with no code.")
            return None
        language = _LANGUAGE_CHARS_RE.sub("", block.language.lower())[:_MAX_LANGUAGE_CHARS]
        return {
            "type": "code",
            "language": language or "text",
            "code": block.code,
            "caption": _or_none(block.caption, _MAX_CAPTION_CHARS),
        }
    if not block.text.strip():
        _add(found, "EMPTY_BLOCK", f"{where} has a callout with no text.")
        return None
    return {
        "type": "callout",
        "kind": block.callout_kind,
        "title": _or_none(block.title, _MAX_CALLOUT_TITLE_CHARS),
        "text": block.text,
    }


def build_lesson(draft: DraftLesson) -> tuple[Lesson | None, list[Violation]]:
    """The stored document for ``draft``, or the list of what is wrong with it.

    Section ids are assigned here ("s1", "s2" ...). Harmless slips are repaired silently: a repeated
    definition or source is dropped, an empty optional field becomes absent, and cosmetic text (a
    callout title, a caption, an analogy) that runs over its limit is trimmed. Anything else that
    does not fit the stored document is reported by where it is ("sections.1.blocks.0.text"), never
    by quoting it, so the writer can ask for exactly that to be fixed.
    """
    found: list[Violation] = []
    sections: list[dict[str, Any]] = []
    for number, draft_section in enumerate(draft.sections, start=1):
        where = f'The section "{draft_section.heading}"'
        blocks = [
            converted
            for block in draft_section.blocks
            if (converted := _convert_block(block, where, found)) is not None
        ]
        if blocks:
            sections.append(
                {"id": f"s{number}", "heading": draft_section.heading, "blocks": blocks}
            )
        else:
            _add(found, "EMPTY_SECTION", f"{where} has no content. Give it text or remove it.")
    if found:
        return None, found

    seen_terms: set[str] = set()
    definitions: list[dict[str, str]] = []
    for definition in draft.definitions:
        key = definition.term.casefold()
        if key not in seen_terms:
            seen_terms.add(key)
            definitions.append({"term": definition.term, "meaning": definition.meaning})

    seen_sources: set[tuple[str, str]] = set()
    references: list[dict[str, Any]] = []
    for reference in draft.source_references:
        pair = (reference.source_id, reference.chunk_id)
        if pair not in seen_sources:
            seen_sources.add(pair)
            references.append(
                {
                    "source_id": reference.source_id,
                    "chunk_id": reference.chunk_id,
                    "note": _or_none(reference.note, _MAX_NOTE_CHARS),
                }
            )

    document: dict[str, Any] = {
        "language": draft.language.strip().lower(),
        "title": draft.title,
        "learning_objectives": draft.learning_objectives,
        "sections": sections,
        "definitions": definitions,
        "worked_examples": [
            {"title": e.title, "problem": e.problem, "steps": e.steps, "answer": e.answer}
            for e in draft.worked_examples
        ],
        "common_misconceptions": [
            {"misconception": m.misconception, "correction": m.correction}
            for m in draft.common_misconceptions
        ],
        "summary": draft.summary,
        "simple_explanation": {
            "paragraphs": draft.simple_explanation.paragraphs,
            "analogy": _or_none(draft.simple_explanation.analogy, _MAX_ANALOGY_CHARS),
        },
        "source_references": references,
    }
    try:
        return Lesson.model_validate(document), []
    except ValidationError as exc:
        problems = [
            Violation(
                "STRUCTURE",
                f"{'.'.join(str(part) for part in error['loc']) or 'lesson'}: {error['msg']}",
            )
            for error in exc.errors(include_input=False, include_url=False)
        ]
        return None, problems[:_MAX_REPORTED]


def validate_lesson(lesson: Lesson, context: LessonContext) -> list[Violation]:
    """Every rule the lesson breaks, or an empty list when it is acceptable."""
    found: list[Violation] = []

    if lesson.language != context.language:
        _add(
            found,
            "LANGUAGE",
            f'The lesson is written in "{lesson.language}", but it must be written in '
            f'"{context.language}", the language of the learner\'s roadmap.',
        )

    headings = Counter(section.heading.casefold() for section in lesson.sections)
    for heading, count in headings.items():
        if count > 1:
            _add(found, "DUPLICATE_HEADING", f'Two sections share the heading "{heading}".')

    for section in lesson.sections:
        words = sum(reading_units(text) for text in _section_prose(section))
        if words < _MIN_SECTION_WORDS:
            _add(
                found,
                "THIN_SECTION",
                f'The section "{section.heading}" is too thin ({words} words). Teach the idea in '
                "a few sentences, or merge the section into another.",
            )

    metrics = measure(lesson)
    if metrics.words < MIN_LESSON_WORDS:
        _add(
            found,
            "TOO_SHORT",
            f"The lesson has about {metrics.words} words, too few to teach the topic. "
            f"Aim for about {context.target_words}.",
        )
    elif metrics.words > context.max_words:
        _add(
            found,
            "TOO_LONG",
            f"The lesson has about {metrics.words} words. Keep it under {context.max_words} "
            f"(aim for about {context.target_words}): cut detail rather than covering less.",
        )

    objectives = Counter(text.casefold() for text in lesson.learning_objectives)
    if any(count > 1 for count in objectives.values()):
        _add(found, "DUPLICATE_OBJECTIVE", "Two learning objectives say the same thing.")

    _check_prose(lesson, context, found)
    _check_sources(lesson, context, found)
    _check_simple_explanation(lesson, found)
    return found[:_MAX_REPORTED]


def _check_prose(lesson: Lesson, context: LessonContext, found: list[Violation]) -> None:
    for where, text in prose_fragments(lesson):
        if _URL_RE.search(text):
            _add(
                found,
                "LINK",
                f"Remove the web address from {where}. Do not include links: they cannot be "
                "checked and may not exist.",
            )
            break
    if not context.evidence:
        for where, text in prose_fragments(lesson):
            if _PUBLICATION_RE.search(text):
                _add(
                    found,
                    "UNSUPPORTED_SOURCE",
                    f"Remove the DOI or ISBN from {where}. No source material was supplied, so "
                    "do not cite publications.",
                )
                break


def _check_sources(lesson: Lesson, context: LessonContext, found: list[Violation]) -> None:
    if not lesson.source_references:
        return
    allowed = context.evidence_ids
    unknown = [
        reference
        for reference in lesson.source_references
        if (reference.source_id, reference.chunk_id) not in allowed
    ]
    if not allowed:
        _add(
            found,
            "UNSUPPORTED_SOURCE",
            "Leave source_references empty: no source material was supplied for this lesson.",
        )
    elif unknown:
        _add(
            found,
            "UNSUPPORTED_SOURCE",
            f"{len(unknown)} source reference(s) point at material that was not supplied. "
            "Cite only the source_id and chunk_id pairs listed under source_material.",
        )


def _check_simple_explanation(lesson: Lesson, found: list[Violation]) -> None:
    simple = " ".join(lesson.simple_explanation.paragraphs)
    if len(simple) < _MIN_SIMPLE_CHARS:
        _add(
            found,
            "SIMPLE_EXPLANATION",
            "The simple explanation is too short to help. Explain the topic in everyday words.",
        )
    summary = " ".join(lesson.summary)
    if simple.casefold().strip() == summary.casefold().strip():
        _add(
            found,
            "SIMPLE_EXPLANATION",
            "The simple explanation just repeats the summary. Re-explain the topic in plainer "
            "words, with a familiar comparison.",
        )
