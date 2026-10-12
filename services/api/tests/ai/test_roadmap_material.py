"""The learner's documents as a contents list for the planner, and the checks that rest on it."""

from typing import Any

from app.ai.fake_roadmap import sample_plan
from app.ai.roadmap.material import (
    MAX_DOCUMENTS,
    MAX_SECTIONS,
    ChunkRef,
    build_material,
    evidence_labels,
    ground_evidence,
    highest_page,
)
from app.ai.roadmap.validation import validate_plan
from support.plans import changed, make_context


def ref(
    index: int,
    title: str | None,
    start: int,
    end: int | None = None,
    *,
    document: str = "doc-a",
    paginated: bool = True,
    page_count: int | None = 20,
) -> ChunkRef:
    return ChunkRef(
        document_id=document,
        document_title=f"Notes {document}",
        paginated=paginated,
        page_count=page_count,
        chunk_id=f"{document}-chunk-{index}",
        page_start=start,
        page_end=end if end is not None else start,
        section_title=title,
    )


def chapters() -> list[ChunkRef]:
    return [
        ref(0, "Basic concepts", 1, 2),
        ref(1, "Basic concepts", 2, 3),
        ref(2, "Normalization", 4, 6),
        ref(3, "Transactions", 7, 7),
    ]


def codes(plan: Any, context: Any) -> set[str]:
    return {violation.code for violation in validate_plan(plan, context)}


# --- The contents list -----------------------------------------------------------------------


def test_passages_of_one_heading_become_one_section_with_its_whole_page_range() -> None:
    (document,) = build_material(chapters())

    assert [(s.label, s.title, s.first_page, s.last_page) for s in document.sections] == [
        ("C1", "Basic concepts", 1, 3),
        ("C2", "Normalization", 4, 6),
        ("C3", "Transactions", 7, 7),
    ]
    assert (document.label, document.document_id) == ("S1", "doc-a")
    # A stored plan points at the section's first passage.
    assert document.sections[0].chunk_id == "doc-a-chunk-0"


def test_a_line_that_is_not_a_heading_is_folded_into_the_section_before() -> None:
    refs = [
        ref(0, "Relational algebra", 1),
        ref(1, "R1 ∩ (R2 ∩ R3)", 2),
        ref(2, "1 55", 3),
        ref(3, None, 4),
        ref(4, "Joins", 5),
    ]

    (document,) = build_material(refs)

    assert [(s.title, s.first_page, s.last_page) for s in document.sections] == [
        ("Relational algebra", 1, 4),
        ("Joins", 5, 5),
    ]


def test_a_document_that_starts_without_a_heading_gets_an_opening_section() -> None:
    (document,) = build_material([ref(0, None, 1), ref(1, "Keys", 2)])

    assert [s.title for s in document.sections] == ["Opening part", "Keys"]


def test_the_planner_sees_labels_titles_and_positions_but_no_real_ids() -> None:
    data = build_material(chapters())[0].as_data()

    assert data == {
        "source": "S1",
        "title": "Notes doc-a",
        "pages": 20,
        "contents": [
            {"id": "C1", "title": "Basic concepts", "where": "pages 1-3"},
            {"id": "C2", "title": "Normalization", "where": "pages 4-6"},
            {"id": "C3", "title": "Transactions", "where": "page 7"},
        ],
    }
    assert "doc-a-chunk" not in str(data)


def test_a_text_without_pages_is_described_in_parts() -> None:
    (document,) = build_material(
        [
            ref(0, "Part one", 1, paginated=False, page_count=None),
            ref(1, "Part two", 2, 3, paginated=False, page_count=None),
        ]
    )

    assert document.as_data()["pages"] is None
    assert [e["where"] for e in document.as_data()["contents"]] == ["part 1", "parts 2-3"]


def test_section_numbers_run_on_across_documents() -> None:
    material = build_material(
        [
            ref(0, "One", 1, document="a"),
            ref(1, "Two", 1, document="b"),
            ref(2, "Three", 2, document="b"),
        ]
    )

    assert [d.label for d in material] == ["S1", "S2"]
    assert [s.label for d in material for s in d.sections] == ["C1", "C2", "C3"]


def test_a_long_contents_list_is_cut_down_by_merging_the_smallest_sections() -> None:
    refs: list[ChunkRef] = []
    for n in range(MAX_SECTIONS + 30):
        # Every section has one passage except section 10, which has three.
        for _ in range(3 if n == 10 else 1):
            refs.append(ref(len(refs), f"Heading number {n}", n + 1, n + 1))

    (document,) = build_material(refs)

    assert len(document.sections) == MAX_SECTIONS
    assert document.sections[0].first_page == 1
    # No page falls into a gap: the list still reaches the last page.
    assert document.sections[-1].last_page == MAX_SECTIONS + 30
    assert any(s.title == "Heading number 10" for s in document.sections)


def test_only_the_first_few_documents_are_used() -> None:
    refs = [ref(n, f"Heading {n}", 1, document=f"doc-{n}") for n in range(MAX_DOCUMENTS + 3)]

    assert len(build_material(refs)) == MAX_DOCUMENTS


def test_nothing_uploaded_is_nothing_to_plan_from() -> None:
    assert build_material([]) == ()
    assert evidence_labels(()) == frozenset()
    assert highest_page(()) == 0


def test_the_highest_page_is_the_documents_own_page_count_or_its_last_section() -> None:
    assert highest_page(build_material(chapters())) == 20
    assert highest_page(build_material([ref(0, "Intro", 1, 9, page_count=None)])) == 9


# --- Real ids replace the labels -------------------------------------------------------------


def test_evidence_labels_are_swapped_for_the_real_document_and_passage_ids() -> None:
    material = build_material(chapters())
    context = make_context(material=material, evidence_ids=evidence_labels(material))
    plan = changed(
        sample_plan(context.input_data()),
        lambda d: d.update(
            evidence=[
                {"source_id": "S1", "chunk_id": "C2"},
                {"source_id": "S1", "chunk_id": "C2"},
                {"source_id": "S1", "chunk_id": "C3"},
                {"source_id": "S9", "chunk_id": "C1"},
            ]
        ),
    )

    grounded = ground_evidence(plan, material)

    assert [(e.source_id, e.chunk_id) for e in grounded.evidence] == [
        ("doc-a", "doc-a-chunk-2"),
        ("doc-a", "doc-a-chunk-3"),
    ]


# --- What the checks require when there is material ------------------------------------------


def material_context() -> Any:
    material = build_material(chapters())
    return make_context(material=material, evidence_ids=evidence_labels(material))


def test_the_sample_plan_follows_the_contents_and_passes_every_check() -> None:
    context = material_context()

    plan = sample_plan(context.input_data())

    assert plan.syllabus_basis == "uploaded_document"
    assert [t.title for t in plan.topics()][:3] == [
        "Part 1: Basic concepts",
        "Part 2: Normalization",
        "Part 3: Transactions",
    ]
    assert plan.evidence
    assert validate_plan(plan, context) == []


def test_a_plan_that_ignores_the_uploaded_material_is_rejected() -> None:
    context = material_context()
    plan = changed(
        sample_plan(context.input_data()),
        lambda d: d.update(evidence=[], syllabus_basis="general_knowledge"),
    )

    assert {"EVIDENCE_REQUIRED", "BASIS_UPLOADED"} <= codes(plan, context)


def test_a_plan_may_not_cite_a_section_that_is_not_in_the_contents() -> None:
    context = material_context()
    plan = changed(
        sample_plan(context.input_data()),
        lambda d: d.update(evidence=[{"source_id": "S1", "chunk_id": "C40"}]),
    )

    assert "EVIDENCE_UNKNOWN" in codes(plan, context)


def test_a_page_the_document_does_not_have_is_rejected() -> None:
    context = material_context()

    def invent_a_page(data: dict[str, Any]) -> None:
        data["modules"][0]["topics"][0]["description"] = "Read pages 18-31 first."

    assert "PAGE_UNKNOWN" in codes(
        changed(sample_plan(context.input_data()), invent_a_page), context
    )


def test_pages_inside_the_document_are_fine() -> None:
    context = material_context()

    def real_pages(data: dict[str, Any]) -> None:
        data["modules"][0]["topics"][0]["description"] = "Read pages 4-6 and then page 7."
        data["modules"][0]["topics"][0]["practice_task"] = "Answer ten questions from pp. 1-3."

    assert validate_plan(changed(sample_plan(context.input_data()), real_pages), context) == []


def test_without_material_page_numbers_are_not_policed() -> None:
    context = make_context()

    def talk_about_a_page(data: dict[str, Any]) -> None:
        data["modules"][0]["topics"][0]["description"] = "Compare with page 400 of your own book."

    assert "PAGE_UNKNOWN" not in codes(
        changed(sample_plan(context.input_data()), talk_about_a_page), context
    )


def test_the_contents_reach_the_prompt_data_only_when_there_is_material() -> None:
    assert "uploaded_material" not in make_context().input_data()
    assert make_context().input_data()["has_uploaded_material"] is False

    data = material_context().input_data()

    assert data["has_uploaded_material"] is True
    assert data["uploaded_material"][0]["contents"][0]["id"] == "C1"
