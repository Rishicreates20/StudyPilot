"""A lesson as PDF study notes (the whole lesson) and as a revision sheet (the essentials)."""

from fpdf.enums import Align

from app.ai.lesson.schema import CalloutBlock, CodeBlock, ListBlock, ParagraphBlock
from app.exports.model import (
    PDF_TYPE,
    LessonSource,
    RenderedFile,
    file_name_for,
    language_name,
    long_date,
)
from app.exports.pdf_base import BODY_FAMILY, LINE, MUTED, DocumentInfo, StudyDocument
from app.schemas.lessons import Citation


def _info(source: LessonSource, kind_label: str) -> DocumentInfo:
    lesson = source.lesson
    facts = [
        ("Topic", source.topic_title),
        ("Goal", source.goal_title),
        ("Lesson version", str(lesson.version)),
        ("Written", long_date(lesson.created_at)),
        ("Language", language_name(lesson.language)),
        ("Based on", _basis(source)),
    ]
    return DocumentInfo(
        title=lesson.content.title,
        subtitle=f"{source.topic_title} - {source.goal_title}",
        kind_label=kind_label,
        language=lesson.language,
        facts=facts,
        is_sample=lesson.is_synthetic,
    )


def _basis(source: LessonSource) -> str:
    grounding = source.lesson.content.grounding
    if grounding == "sources":
        return "Your uploaded study material, with the passages listed under Sources"
    if grounding == "no_match":
        return "General knowledge: your uploaded material did not cover this topic"
    return "General knowledge (no uploaded material was used)"


def _citation_line(label: str, citation: Citation) -> str:
    if not citation.available:
        return f"{label}: no longer available (the document was deleted)"
    parts = [citation.document_title or "Untitled document"]
    if citation.position:
        parts.append(citation.position)
    line = f"{label}: " + ", ".join(parts)
    if citation.note:
        line += f" - {citation.note}"
    return line


def _sources(pdf: StudyDocument, source: LessonSource) -> None:
    pdf.heading("Sources")
    citations = source.lesson.citations
    if not citations:
        pdf.paragraph(
            "This lesson does not cite any of your documents. It was written with AI help from "
            "general knowledge, so check important facts against your course material.",
            muted=True,
        )
        return
    pdf.bullets([_citation_line(f"[{n}]", c) for n, c in enumerate(citations, start=1)])


def render_notes(source: LessonSource) -> RenderedFile:
    lesson = source.lesson.content
    pdf = StudyDocument(_info(source, "Study notes"))
    pdf.title_page()
    pdf.add_page()

    pdf.heading("What you will learn")
    pdf.bullets(lesson.learning_objectives)

    for section in lesson.sections:
        pdf.heading(section.heading)
        for block in section.blocks:
            if isinstance(block, ParagraphBlock):
                pdf.paragraph(block.text)
            elif isinstance(block, ListBlock):
                pdf.bullets(block.items, ordered=block.ordered)
            elif isinstance(block, CodeBlock):
                pdf.code(block.code, caption=block.caption, language=block.language)
            elif isinstance(block, CalloutBlock):  # pyright: ignore[reportUnnecessaryIsInstance]
                pdf.callout(block.kind, block.text, title=block.title)

    simple = lesson.simple_explanation
    pdf.heading("In simple terms")
    for text in simple.paragraphs:
        pdf.paragraph(text)
    if simple.analogy:
        pdf.callout("tip", simple.analogy, title="Think of it like this")

    if lesson.definitions:
        pdf.heading("Key terms")
        pdf.data_table(
            ("Term", "Meaning"),
            [(d.term, d.meaning) for d in lesson.definitions],
            widths=(30, 70),
        )

    pdf.heading("Worked examples")
    for example in lesson.worked_examples:
        pdf.heading(example.title, level=2)
        pdf.label_value("Problem:", example.problem)
        pdf.bullets(example.steps, ordered=True)
        pdf.label_value("Answer:", example.answer)

    if lesson.common_misconceptions:
        pdf.heading("Common misconceptions")
        pdf.data_table(
            ("It is tempting to think", "In fact"),
            [(m.misconception, m.correction) for m in lesson.common_misconceptions],
            widths=(45, 55),
        )

    pdf.heading("Summary")
    pdf.bullets(lesson.summary)
    _sources(pdf, source)

    data = pdf.render()
    return RenderedFile(
        data=data,
        content_type=PDF_TYPE,
        file_name=file_name_for(lesson.title, "notes", "pdf"),
        page_count=pdf.pages_count,
        unsupported_characters=pdf.guard.unsupported,
    )


def _checklist(pdf: StudyDocument, items: list[str]) -> None:
    """Items with an empty box to tick on paper (a drawn square: no font needs a glyph)."""
    pdf.set_font(BODY_FAMILY, "", 9.5)
    for item in items:
        y = pdf.get_y()
        pdf.set_draw_color(*MUTED)
        pdf.rect(pdf.l_margin + 1, y + 1.2, 3.2, 3.2)
        pdf.set_x(pdf.l_margin + 7)
        pdf.multi_cell(pdf.epw - 7, LINE * 0.9, pdf.guard.clean(item), align=Align.L)
        pdf.set_x(pdf.l_margin)
        pdf.ln(1)


def render_revision(source: LessonSource) -> RenderedFile:
    """A compact sheet to revise from: no title page, the essentials only, smaller type."""
    lesson = source.lesson.content
    pdf = StudyDocument(_info(source, "Revision sheet"))
    pdf.add_page()
    pdf.set_font(BODY_FAMILY, "B", 17)
    pdf.multi_cell(0, 8, pdf.guard.clean(lesson.title), align=Align.L)
    pdf.set_x(pdf.l_margin)
    pdf.paragraph(
        f"Revision sheet - {source.topic_title} - {source.goal_title}", size=9, muted=True
    )
    if source.lesson.is_synthetic:
        pdf.callout(
            "warning",
            "Made from sample content written by the built-in test provider. Not real study "
            "material.",
            title="Sample content",
        )

    pdf.heading("Key points", level=2)
    pdf.bullets(lesson.summary, size=9.5)

    if lesson.definitions:
        pdf.heading("Key terms", level=2)
        pdf.data_table(
            ("Term", "Meaning"),
            [(d.term, d.meaning) for d in lesson.definitions],
            widths=(28, 72),
            size=8.5,
        )

    if lesson.common_misconceptions:
        pdf.heading("Watch out for", level=2)
        pdf.data_table(
            ("Mistake", "Correct idea"),
            [(m.misconception, m.correction) for m in lesson.common_misconceptions],
            widths=(45, 55),
            size=8.5,
        )

    pdf.heading("Examples in brief", level=2)
    for example in lesson.worked_examples:
        pdf.label_value(f"{example.title}:", example.problem)
        pdf.label_value("Answer:", example.answer)

    pdf.heading("Check yourself", level=2)
    pdf.paragraph("Tick each one you can do without looking at your notes.", size=9, muted=True)
    _checklist(pdf, list(lesson.learning_objectives))

    if source.lesson.citations:
        pdf.heading("Sources", level=2)
        pdf.bullets(
            [_citation_line(f"[{n}]", c) for n, c in enumerate(source.lesson.citations, 1)],
            size=8.5,
        )

    data = pdf.render()
    return RenderedFile(
        data=data,
        content_type=PDF_TYPE,
        file_name=file_name_for(lesson.title, "revision", "pdf"),
        page_count=pdf.pages_count,
        unsupported_characters=pdf.guard.unsupported,
    )
