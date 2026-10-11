"""The lesson document and the code-side checks on a model's draft."""

from typing import Any, cast

import pytest
from pydantic import ValidationError

from app.ai.lesson.context import EvidenceChunk
from app.ai.lesson.schema import (
    Adjust,
    CalloutBlock,
    CodeBlock,
    DraftLesson,
    Lesson,
    LessonSection,
    ListBlock,
    ParagraphBlock,
)
from app.ai.lesson.validation import (
    build_lesson,
    measure,
    prose_fragments,
    reading_units,
    validate_lesson,
)
from app.ai.schema_utils import provider_schema
from support.lessons import changed, make_context, valid_draft, valid_lesson

LONG = (
    "This sentence repeats on purpose so that the section has enough words to count as real "
    "teaching and not as a heading with a stub underneath it. "
)


def codes(violations: list[Any]) -> set[str]:
    return {violation.code for violation in violations}


def lesson_from(draft: DraftLesson) -> Lesson:
    lesson, violations = build_lesson(draft)
    assert lesson is not None, violations
    return lesson


# --- The sample is a good lesson ---------------------------------------------------------------


def test_the_built_in_sample_lesson_passes_every_check() -> None:
    context = make_context()
    lesson = valid_lesson(context)

    assert validate_lesson(lesson, context) == []


@pytest.mark.parametrize("minutes", [5, 30, 120, 480])
def test_the_sample_fits_any_topic_length(minutes: int) -> None:
    context = make_context(estimated_minutes=minutes)

    assert validate_lesson(valid_lesson(context), context) == []


@pytest.mark.parametrize("adjust", ["simpler", "more_examples", "deeper"])
def test_every_adjustment_still_produces_a_valid_lesson(adjust: Adjust) -> None:
    context = make_context(adjust=adjust)

    assert validate_lesson(valid_lesson(context), context) == []


# --- Building the stored document ------------------------------------------------------------


def test_sections_get_stable_ids_in_order() -> None:
    lesson = valid_lesson()

    assert [section.id for section in lesson.sections] == [
        f"s{n}" for n in range(1, len(lesson.sections) + 1)
    ]
    assert lesson.section_ids() == [section.id for section in lesson.sections]


def test_a_block_is_converted_to_its_own_typed_shape() -> None:
    lesson = valid_lesson()
    blocks = [block for section in lesson.sections for block in section.blocks]

    assert any(isinstance(block, ParagraphBlock) for block in blocks)
    assert any(isinstance(block, ListBlock) and block.ordered for block in blocks)
    assert any(isinstance(block, CodeBlock) and block.language == "text" for block in blocks)


@pytest.mark.parametrize(
    ("block", "message"),
    [
        ({"type": "paragraph", "text": "  "}, "paragraph with no text"),
        ({"type": "list", "items": ["", "   "]}, "list with no items"),
        ({"type": "code", "code": "\n"}, "code block with no code"),
        ({"type": "callout", "callout_kind": "tip", "text": ""}, "callout with no text"),
    ],
)
def test_a_block_missing_what_its_type_needs_is_reported(
    block: dict[str, Any], message: str
) -> None:
    draft = changed(valid_draft(), lambda d: d["sections"][1]["blocks"].append(block))

    lesson, violations = build_lesson(draft)

    assert lesson is None
    assert codes(violations) == {"EMPTY_BLOCK"}
    assert message in violations[0].message
    assert "The main idea" in violations[0].message


def test_a_section_with_nothing_in_it_is_reported() -> None:
    def edit(d: dict[str, Any]) -> None:
        d["sections"][2]["blocks"] = [{"type": "paragraph", "text": ""}]

    lesson, violations = build_lesson(changed(valid_draft(), edit))

    assert lesson is None
    assert codes(violations) == {"EMPTY_BLOCK", "EMPTY_SECTION"}


def test_a_repeated_definition_or_source_is_dropped_not_rejected() -> None:
    def edit(d: dict[str, Any]) -> None:
        d["definitions"] = [
            {"term": "Borrow", "meaning": "Use a value without taking it."},
            {"term": "BORROW", "meaning": "The same word, shouted."},
        ]
        d["source_references"] = [
            {"source_id": "a", "chunk_id": "1"},
            {"source_id": "a", "chunk_id": "1", "note": "again"},
        ]

    lesson = lesson_from(changed(valid_draft(), edit))

    assert [d.term for d in lesson.definitions] == ["Borrow"]
    assert len(lesson.source_references) == 1


def test_a_code_language_is_normalised_and_an_empty_one_means_plain_text() -> None:
    def edit(d: dict[str, Any]) -> None:
        d["sections"][0]["blocks"] += [
            {"type": "code", "language": " Python!! ", "code": "print(1)"},
            {"type": "code", "language": "", "code": "output"},
        ]

    lesson = lesson_from(changed(valid_draft(), edit))

    languages = [
        block.language
        for section in lesson.sections
        for block in section.blocks
        if isinstance(block, CodeBlock)
    ]
    assert languages[:2] == ["python", "text"]


def test_empty_optional_fields_become_absent() -> None:
    lesson = lesson_from(valid_draft())
    block = next(b for s in lesson.sections for b in s.blocks if isinstance(b, CodeBlock))

    assert block.caption == "Placeholder for a real code example"
    plain = lesson_from(
        changed(
            valid_draft(),
            lambda d: d["simple_explanation"].update(analogy=""),
        )
    )
    assert plain.simple_explanation.analogy is None


# --- The stored document is strict -----------------------------------------------------------


def test_the_stored_document_refuses_an_unknown_block_type() -> None:
    data = valid_lesson().model_dump(mode="json")
    data["sections"][0]["blocks"][0] = {"type": "video", "url": "https://example.com"}

    with pytest.raises(ValidationError):
        Lesson.model_validate(data)


def test_the_stored_document_refuses_fields_it_does_not_define() -> None:
    data = valid_lesson().model_dump(mode="json")
    data["sections"][0]["html"] = "<script>alert(1)</script>"

    with pytest.raises(ValidationError):
        Lesson.model_validate(data)


def test_a_stored_document_round_trips_unchanged() -> None:
    lesson = valid_lesson()

    assert Lesson.model_validate(lesson.model_dump(mode="json")) == lesson


@pytest.mark.parametrize("section_id", ["1", "section-1", "s", "s123", "S1"])
def test_a_section_id_must_look_like_one(section_id: str) -> None:
    with pytest.raises(ValidationError):
        LessonSection(id=section_id, heading="Heading", blocks=[ParagraphBlock(text="x")])


# --- The checks ------------------------------------------------------------------------------


def test_a_lesson_in_the_wrong_language_is_rejected() -> None:
    context = make_context(language="hi")
    lesson = valid_lesson(make_context(language="en"))

    assert "LANGUAGE" in codes(validate_lesson(lesson, context))


def test_two_sections_cannot_share_a_heading() -> None:
    def edit(d: dict[str, Any]) -> None:
        d["sections"][1]["heading"] = d["sections"][0]["heading"].upper()

    lesson = lesson_from(changed(valid_draft(), edit))

    assert "DUPLICATE_HEADING" in codes(validate_lesson(lesson, make_context()))


def test_a_section_that_is_only_a_line_is_too_thin() -> None:
    def edit(d: dict[str, Any]) -> None:
        d["sections"][2]["blocks"] = [{"type": "paragraph", "text": "Just this."}]

    lesson = lesson_from(changed(valid_draft(), edit))

    violations = validate_lesson(lesson, make_context())
    assert "THIN_SECTION" in codes(violations)
    assert any("A small example" in v.message for v in violations)


def test_a_section_of_only_code_is_too_thin() -> None:
    def edit(d: dict[str, Any]) -> None:
        d["sections"][2]["blocks"] = [{"type": "code", "language": "python", "code": "x = 1" * 80}]

    lesson = lesson_from(changed(valid_draft(), edit))

    assert "THIN_SECTION" in codes(validate_lesson(lesson, make_context()))


def test_a_lesson_far_too_short_to_teach_anything_is_rejected() -> None:
    def edit(d: dict[str, Any]) -> None:
        d["sections"] = [
            {
                "heading": "One",
                "blocks": [{"type": "paragraph", "text": "Short but fifteen words " * 1}],
            },
            {
                "heading": "Two",
                "blocks": [{"type": "paragraph", "text": "Also very short indeed."}],
            },
        ]
        d["definitions"] = []
        d["worked_examples"] = [
            {
                "title": "Example",
                "problem": "A problem of ten letters.",
                "steps": ["Do."],
                "answer": "Done.",
            }
        ]
        d["common_misconceptions"] = []
        d["summary"] = ["One idea here.", "Another idea here."]
        d["simple_explanation"] = {
            "paragraphs": ["Tiny words for tiny people. " * 3],
            "analogy": "",
        }

    lesson = lesson_from(changed(valid_draft(), edit))

    assert "TOO_SHORT" in codes(validate_lesson(lesson, make_context()))


def test_a_lesson_far_over_its_budget_is_rejected_with_the_budget_in_the_message() -> None:
    context = make_context(estimated_minutes=10)  # target 350 words, up to 700

    def edit(d: dict[str, Any]) -> None:
        d["sections"][1]["blocks"] = [{"type": "paragraph", "text": LONG * 20}] * 2

    lesson = lesson_from(changed(valid_draft(context), edit))

    violations = validate_lesson(lesson, context)
    assert "TOO_LONG" in codes(violations)
    assert str(context.max_words) in next(v.message for v in violations if v.code == "TOO_LONG")


def test_a_web_address_in_the_prose_is_rejected_but_one_in_code_is_fine() -> None:
    def link(d: dict[str, Any]) -> None:
        d["sections"][1]["blocks"][0]["text"] += " See https://example.com/docs for more."

    def code(d: dict[str, Any]) -> None:
        d["sections"][2]["blocks"].append(
            {"type": "code", "language": "bash", "code": "curl https://example.com/api"}
        )

    context = make_context()
    assert "LINK" in codes(validate_lesson(lesson_from(changed(valid_draft(), link)), context))
    assert validate_lesson(lesson_from(changed(valid_draft(), code)), context) == []


@pytest.mark.parametrize("text", ["Read www.example.org today.", "Visit HTTP://EXAMPLE.COM now."])
def test_links_are_found_whatever_their_spelling(text: str) -> None:
    def edit(d: dict[str, Any]) -> None:
        d["summary"][0] = text

    lesson = lesson_from(changed(valid_draft(), edit))

    assert "LINK" in codes(validate_lesson(lesson, make_context()))


def test_a_doi_or_isbn_is_rejected_when_no_source_material_was_given() -> None:
    def edit(d: dict[str, Any]) -> None:
        d["sections"][0]["blocks"][0]["text"] += " (doi:10.1000/182)"

    lesson = lesson_from(changed(valid_draft(), edit))

    assert "UNSUPPORTED_SOURCE" in codes(validate_lesson(lesson, make_context()))


# --- Citations -------------------------------------------------------------------------------

EVIDENCE = (EvidenceChunk("doc-1", "chunk-7", "My notes", "Ownership means one owner."),)


def with_reference(source_id: str, chunk_id: str) -> DraftLesson:
    def edit(d: dict[str, Any]) -> None:
        d["source_references"] = [{"source_id": source_id, "chunk_id": chunk_id, "note": "x"}]

    return changed(valid_draft(), edit)


def test_a_citation_is_rejected_when_no_source_material_was_supplied() -> None:
    lesson = lesson_from(with_reference("doc-1", "chunk-7"))

    violations = validate_lesson(lesson, make_context())

    assert codes(violations) == {"UNSUPPORTED_SOURCE"}
    assert "empty" in violations[0].message


def test_a_citation_of_supplied_material_is_accepted() -> None:
    context = make_context(evidence=EVIDENCE)
    lesson = lesson_from(with_reference("doc-1", "chunk-7"))

    assert validate_lesson(lesson, context) == []
    assert lesson.source_references[0].source_id == "doc-1"


@pytest.mark.parametrize(
    ("source_id", "chunk_id"), [("doc-1", "chunk-8"), ("doc-2", "chunk-7"), ("made-up", "made-up")]
)
def test_a_citation_of_material_that_was_not_supplied_is_rejected(
    source_id: str, chunk_id: str
) -> None:
    context = make_context(evidence=EVIDENCE)
    lesson = lesson_from(with_reference(source_id, chunk_id))

    violations = validate_lesson(lesson, context)

    assert codes(violations) == {"UNSUPPORTED_SOURCE"}
    assert "not supplied" in violations[0].message


def test_no_citation_is_needed_even_when_material_was_supplied() -> None:
    context = make_context(evidence=EVIDENCE)

    assert validate_lesson(valid_lesson(context), context) == []


# --- The simple explanation ------------------------------------------------------------------


def test_a_simple_explanation_that_says_almost_nothing_is_rejected() -> None:
    lesson = lesson_from(
        changed(
            valid_draft(),
            lambda d: d["simple_explanation"].update(paragraphs=["It is easy."], analogy=""),
        )
    )

    assert "SIMPLE_EXPLANATION" in codes(validate_lesson(lesson, make_context()))


def test_a_simple_explanation_that_only_repeats_the_summary_is_rejected() -> None:
    def edit(d: dict[str, Any]) -> None:
        d["summary"] = [
            "Ownership gives each value exactly one owner at a time.",
            "Borrowing lets others look.",
        ]
        d["simple_explanation"]["paragraphs"] = [" ".join(d["summary"])]

    lesson = lesson_from(changed(valid_draft(), edit))

    violations = validate_lesson(lesson, make_context())
    assert "SIMPLE_EXPLANATION" in codes(violations)
    assert any("repeats the summary" in v.message for v in violations)


def test_duplicate_learning_objectives_are_rejected() -> None:
    lesson = lesson_from(
        changed(
            valid_draft(),
            lambda d: d.update(learning_objectives=["Explain the idea", "explain the IDEA"]),
        )
    )

    assert "DUPLICATE_OBJECTIVE" in codes(validate_lesson(lesson, make_context()))


# --- Measuring -------------------------------------------------------------------------------


def test_words_are_counted_across_every_piece_of_prose_but_not_code() -> None:
    lesson = valid_lesson()
    with_code = lesson_from(
        changed(
            valid_draft(),
            lambda d: d["sections"][2]["blocks"].append(
                {"type": "code", "language": "python", "code": "x = 1 " * 500}
            ),
        )
    )

    assert measure(lesson).words == measure(with_code).words
    assert measure(with_code).code_blocks == measure(lesson).code_blocks + 1
    assert measure(lesson).sections == len(lesson.sections)
    assert len(list(prose_fragments(lesson))) > 10


@pytest.mark.parametrize(
    ("text", "expected"),
    [("", 0), ("one two three", 3), ("a" * 100, 50), ("日本語のテキストです" * 10, 50)],
)
def test_reading_units_handles_scripts_written_without_spaces(text: str, expected: int) -> None:
    assert reading_units(text) == expected


# --- What the provider is sent ---------------------------------------------------------------


def test_the_schema_sent_to_the_provider_uses_only_the_safe_subset() -> None:
    schema = provider_schema(DraftLesson)
    allowed = {
        "type", "properties", "required", "items", "enum", "minimum", "maximum", "minItems",
        "description",
    }  # fmt: skip

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            mapping = cast(dict[str, Any], node)
            keys = set(mapping) - {"properties"}
            assert keys <= allowed, keys - allowed
            for name, child in mapping.items():
                if name == "properties":
                    for grandchild in cast(dict[str, Any], child).values():
                        walk(grandchild)
                else:
                    walk(child)
        elif isinstance(node, list):
            for item in cast(list[Any], node):
                walk(item)

    walk(schema)
    assert "$ref" not in str(schema) and "anyOf" not in str(schema) and "oneOf" not in str(schema)
    assert {"sections", "worked_examples", "simple_explanation"} <= set(schema["required"])
    block = schema["properties"]["sections"]["items"]["properties"]["blocks"]["items"]
    assert block["properties"]["type"]["enum"] == ["paragraph", "list", "code", "callout"]
    assert block["required"] == ["type"]


# --- Limits: trim what is cosmetic, report where the rest is too long ---------------------------


def test_cosmetic_text_over_its_limit_is_trimmed_not_sent_back_for_repair() -> None:
    def edit(d: dict[str, Any]) -> None:
        d["sections"][0]["blocks"][1]["title"] = "T" * 150  # a callout title (limit 100)
        d["sections"][2]["blocks"][1]["caption"] = "C" * 300  # a code caption (limit 200)
        d["sections"][2]["blocks"][1]["language"] = "python-" * 10  # a code language (limit 30)
        d["simple_explanation"]["analogy"] = "A" * 900  # an analogy (limit 500)
        d["source_references"] = [{"source_id": "s", "chunk_id": "c", "note": "N" * 400}]

    lesson = lesson_from(changed(valid_draft(), edit))

    callout = lesson.sections[0].blocks[1]
    code = lesson.sections[2].blocks[1]
    assert isinstance(callout, CalloutBlock) and callout.title is not None
    assert len(callout.title) == 100 and callout.title.endswith("…")
    assert isinstance(code, CodeBlock) and code.caption is not None and len(code.caption) == 200
    assert len(code.language) <= 30
    assert lesson.simple_explanation.analogy is not None
    assert len(lesson.simple_explanation.analogy) == 500
    assert lesson.source_references[0].note is not None
    assert len(lesson.source_references[0].note or "") == 200


def test_content_that_is_too_long_is_reported_by_where_it_is_and_never_quoted() -> None:
    secret = "the model's own words that must not be echoed " * 120  # about 5,500 characters

    def edit(d: dict[str, Any]) -> None:
        d["sections"][1]["blocks"][0]["text"] = secret
        d["definitions"][0:] = [{"term": "Borrow", "meaning": "M" * 700}]

    lesson, violations = build_lesson(changed(valid_draft(), edit))

    assert lesson is None
    assert codes(violations) == {"STRUCTURE"}
    messages = " | ".join(v.message for v in violations)
    assert "sections.1.blocks.0.paragraph.text" in messages
    assert "definitions.0.meaning" in messages
    assert "must not be echoed" not in messages


def test_the_draft_the_model_fills_in_is_looser_than_the_stored_document() -> None:
    def edit(d: dict[str, Any]) -> None:
        d["sections"][0]["blocks"][1]["title"] = "T" * 150
        d["learning_objectives"][0] = "O" * 350

    draft = changed(valid_draft(), edit)  # does not raise

    lesson, violations = build_lesson(draft)
    assert lesson is None  # 350 characters is too long for a stored objective ...
    assert [v.message.split(":")[0] for v in violations] == ["learning_objectives.0"]
