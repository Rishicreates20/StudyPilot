"""Lessons and roadmaps as PowerPoint presentations.

Two steps, so each can be tested on its own:

1. ``lesson_outline`` / ``roadmap_outline`` turn structured content into a list of ``Slide``s: a
   sensible deck, not a lesson pasted onto one slide. A slide carries at most ``MAX_POINTS`` short
   points; a long paragraph becomes its first sentence on the slide and its full text in the
   speaker notes; code gets its own slide; anything longer continues on a "(continued)" slide.
2. ``write_pptx`` draws the outline on 16:9 slides with python-pptx.

A .pptx cannot embed fonts (python-pptx has no way to), so the viewer's fonts render it. Latin text
names Calibri, and Hindi and Odia runs name Nirmala UI as their complex-script font (installed with
Windows); other systems substitute their own Devanagari or Odia font. This is a known limit, unlike
the PDFs, which embed Noto fonts.
"""

import io
import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.xmlchemy import OxmlElement
from pptx.slide import Slide as PptxSlide
from pptx.text.text import TextFrame, _Run  # pyright: ignore[reportPrivateUsage]
from pptx.util import Emu, Inches, Pt

from app.ai.lesson.schema import CalloutBlock, CodeBlock, ListBlock, ParagraphBlock
from app.exports.model import PPTX_TYPE, LessonSource, RenderedFile, RoadmapSource, file_name_for
from app.exports.typography import script_of

MAX_POINTS = 5
MAX_POINT_CHARS = 150
MAX_CODE_LINES = 16
MAX_CODE_COLUMNS = 72

SlideKind = Literal["title", "points", "code"]
_CALLOUT_LABELS = {"tip": "Tip", "note": "Note", "warning": "Watch out"}
_SENTENCE_END = re.compile(r"(?<=[.!?।॥])\s+")


@dataclass
class Slide:
    kind: SlideKind
    title: str
    points: list[str] = field(default_factory=list[str])
    subtitle: str | None = None
    code: str | None = None
    caption: str | None = None
    notes: str | None = None


# --- Text helpers ----------------------------------------------------------------------------


def plain(text: str) -> str:
    """NFC text without control or format characters (XML forbids most of them), joiners kept."""
    out: list[str] = []
    for char in unicodedata.normalize("NFC", text):
        if char in "\u200c\u200d":
            out.append(char)
        elif char in "\n\t":
            out.append(" ")
        elif unicodedata.category(char) in {"Cc", "Cf", "Cs", "Co"}:
            continue
        else:
            out.append(char)
    return re.sub(r"\s+", " ", "".join(out)).strip()


def shorten(text: str, limit: int = MAX_POINT_CHARS) -> str:
    """``text`` cut at a word boundary to at most ``limit`` characters, with an ellipsis."""
    text = plain(text)
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    space = cut.rfind(" ")
    if space > limit // 2:
        cut = cut[:space]
    return cut.rstrip(" ,;:-") + "…"


def first_sentence(text: str, limit: int = MAX_POINT_CHARS) -> str:
    sentences = _SENTENCE_END.split(plain(text), maxsplit=1)
    return shorten(sentences[0] if sentences else text, limit)


def _chunked(
    title: str, points: Sequence[str], *, notes: str | None = None, size: int = MAX_POINTS
) -> list[Slide]:
    """``points`` spread over as many slides as needed, the later ones marked as continued."""
    if not points:
        return []
    slides: list[Slide] = []
    for start in range(0, len(points), size):
        heading = title if start == 0 else f"{title} (continued)"
        slides.append(
            Slide(
                kind="points",
                title=heading,
                points=list(points[start : start + size]),
                notes=notes if start == 0 else None,
            )
        )
    return slides


def code_text(code: str) -> str:
    """Code with its line breaks and indentation, without other control or format characters.

    python-pptx would not fail on them, but it writes them out as visible ``_x0001_`` text."""
    return "".join(
        char
        for char in unicodedata.normalize("NFC", code.replace("\r\n", "\n"))
        if char in "\n\t‌‍" or unicodedata.category(char) not in {"Cc", "Cf", "Cs", "Co"}
    )


def _code_slide(title: str, block: CodeBlock) -> Slide:
    code = code_text(block.code)
    lines = code.expandtabs(4).rstrip("\n").splitlines()
    shortened = len(lines) > MAX_CODE_LINES or any(len(line) > MAX_CODE_COLUMNS for line in lines)
    shown = [
        line if len(line) <= MAX_CODE_COLUMNS else line[: MAX_CODE_COLUMNS - 1] + "…"
        for line in lines[:MAX_CODE_LINES]
    ]
    caption = block.caption or block.language
    if shortened:
        caption = f"{caption} - shortened; the full code is in the speaker notes and the PDF notes"
    return Slide(
        kind="code",
        title=f"{title}: example",
        code="\n".join(shown),
        caption=caption,
        notes=code if shortened else None,
    )


# --- Outlines ----------------------------------------------------------------------------------


def lesson_outline(source: LessonSource) -> list[Slide]:
    lesson = source.lesson.content
    sample = " (sample content from the test provider)" if source.lesson.is_synthetic else ""
    slides = [
        Slide(
            kind="title",
            title=lesson.title,
            subtitle=f"{source.topic_title} - {source.goal_title}{sample}",
        )
    ]
    slides += _chunked("What you will learn", [shorten(o) for o in lesson.learning_objectives])

    for section in lesson.sections:
        points: list[str] = []
        notes: list[str] = []
        code_slides: list[Slide] = []
        for block in section.blocks:
            if isinstance(block, ParagraphBlock):
                points.append(first_sentence(block.text))
                notes.append(plain(block.text))
            elif isinstance(block, ListBlock):
                points.extend(shorten(item, 120) for item in block.items)
                # A point may be cut short on the slide; the notes keep every item in full.
                notes.append("\n".join(f"- {plain(item)}" for item in block.items))
            elif isinstance(block, CalloutBlock):
                label = block.title or _CALLOUT_LABELS.get(block.kind, "Note")
                points.append(f"{plain(label)}: {first_sentence(block.text, 120)}")
                notes.append(plain(block.text))
            elif isinstance(block, CodeBlock):  # pyright: ignore[reportUnnecessaryIsInstance]
                code_slides.append(_code_slide(section.heading, block))
        slides += _chunked(section.heading, points, notes="\n\n".join(notes) or None)
        slides += code_slides

    simple = lesson.simple_explanation
    simple_points = [first_sentence(p) for p in simple.paragraphs]
    if simple.analogy:
        simple_points.append(f"Think of it like this: {first_sentence(simple.analogy, 130)}")
    slides += _chunked(
        "In simple terms",
        simple_points,
        notes="\n\n".join(plain(p) for p in simple.paragraphs),
    )

    slides += _chunked(
        "Key terms",
        [f"{plain(d.term)}: {shorten(d.meaning, 120)}" for d in lesson.definitions],
    )
    for example in lesson.worked_examples:
        points = [f"Problem: {shorten(example.problem, 140)}"]
        points += [shorten(step, 110) for step in example.steps]
        points.append(f"Answer: {shorten(example.answer, 140)}")
        slides += _chunked(
            f"Worked example: {plain(example.title)}",
            points,
            notes=f"{plain(example.problem)}\n\n{plain(example.answer)}",
        )
    slides += _chunked(
        "Common misconceptions",
        [
            f"Not: {shorten(m.misconception, 70)} Instead: {shorten(m.correction, 75)}"
            for m in lesson.common_misconceptions
        ],
        size=3,
    )
    slides += _chunked("Summary", [shorten(point) for point in lesson.summary], size=6)
    citations = source.lesson.citations
    if citations:
        slides += _chunked(
            "Sources",
            [
                shorten(
                    f"[{n}] {c.document_title or 'Untitled document'}"
                    + (f", {c.position}" if c.position else "")
                    if c.available
                    else f"[{n}] no longer available"
                )
                for n, c in enumerate(citations, start=1)
            ],
            size=6,
        )
    return slides


def roadmap_outline(source: RoadmapSource) -> list[Slide]:
    roadmap = source.roadmap
    sample = " (sample content from the test provider)" if roadmap.is_synthetic else ""
    slides = [
        Slide(
            kind="title",
            title=roadmap.title,
            subtitle=(
                f"{source.goal_title} - {roadmap.total_days} days, about "
                f"{roadmap.daily_minutes} minutes a day{sample}"
            ),
        )
    ]
    overview = [first_sentence(s) for s in _SENTENCE_END.split(plain(roadmap.overview))][:4]
    overview.append(f"Where this takes you: {shorten(roadmap.target_outcome, 120)}")
    slides += _chunked("Overview", overview, notes=plain(roadmap.overview))
    slides += _chunked(
        "Learning objectives",
        [f"{o.id.upper()}: {shorten(o.text, 130)}" for o in roadmap.objectives],
        size=6,
    )
    for module in roadmap.modules:
        points = [
            shorten(
                (f"Day {t.day_number}: " if t.day_number is not None else "")
                + f"{plain(t.title)} ({t.estimated_minutes} min)",
                120,
            )
            for t in module.topics
        ]
        # The slide lists the topics; the notes say what each one is and what to practise.
        topic_notes = [
            f"{plain(t.title)}: {plain(t.description)}"
            + (f"\nPractice: {plain(t.practice_task)}" if t.practice_task else "")
            for t in module.topics
        ]
        slides += _chunked(
            f"Module {module.position}: {plain(module.title)}",
            points,
            notes="\n\n".join([plain(module.summary), *topic_notes]),
            size=6,
        )
    slides += _chunked(
        "Revision sessions",
        [
            shorten(
                (f"Day {r.day_number}: " if r.day_number is not None else "") + plain(r.title), 120
            )
            for r in roadmap.revision_sessions
        ],
        size=6,
    )
    slides += _chunked(
        "Optional extras", [shorten(e.title, 120) for e in roadmap.enrichment], size=6
    )
    slides += _chunked(
        "Check these yourself",
        [shorten(a) for a in (*roadmap.assumptions, *roadmap.unknowns)],
    )
    return slides


# --- Writing the .pptx -------------------------------------------------------------------------

_ACCENT = RGBColor(0x34, 0x40, 0x9C)
_INK = RGBColor(0x21, 0x25, 0x29)
_MUTED = RGBColor(0x60, 0x67, 0x70)
_CODE_BG = RGBColor(0xF3, 0xF4, 0xF6)
_WIDTH = Inches(13.333)
_HEIGHT = Inches(7.5)
_MARGIN = Inches(0.7)
_COMPLEX_SCRIPT_FONT = "Nirmala UI"
_LANG = {"deva": "hi-IN", "orya": "or-IN", "latn": "en-GB"}


def _xml(element: object) -> Any:
    """python-pptx elements are lxml elements, for which there is no type information here."""
    return element


def _style_run(
    run_text: str, run: _Run, *, size: int, bold: bool, colour: RGBColor, font: str
) -> None:
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = colour
    run.font.name = font
    script = script_of(run_text)
    r_pr = _xml(run._r.get_or_add_rPr())  # pyright: ignore[reportPrivateUsage]
    r_pr.set("lang", _LANG[script])
    if script != "latn":
        # Complex scripts take their font from <a:cs>, not from <a:latin>.
        complex_script = _xml(OxmlElement("a:cs"))
        complex_script.set("typeface", _COMPLEX_SCRIPT_FONT)
        r_pr.append(complex_script)


def _paragraphs(
    frame: TextFrame,
    texts: Iterable[str],
    *,
    size: int,
    bold: bool = False,
    colour: RGBColor = _INK,
    font: str = "Calibri",
    bullet: bool = False,
    space_after: int = 10,
) -> None:
    frame.word_wrap = True
    first = True
    for text in texts:
        paragraph = frame.paragraphs[0] if first else frame.add_paragraph()
        first = False
        paragraph.space_after = Pt(space_after)
        if bullet:
            p_pr = _xml(paragraph._p.get_or_add_pPr())  # pyright: ignore[reportPrivateUsage]
            p_pr.set("marL", str(Inches(0.35)))
            p_pr.set("indent", str(-Inches(0.3)))
            bullet_font = _xml(OxmlElement("a:buFont"))
            bullet_font.set("typeface", "Arial")
            p_pr.append(bullet_font)
            bullet_char = _xml(OxmlElement("a:buChar"))
            bullet_char.set("char", "•")
            p_pr.append(bullet_char)
        run = paragraph.add_run()
        run.text = text
        _style_run(text, run, size=size, bold=bold, colour=colour, font=font)


def _furniture(slide: PptxSlide, number: int, total: int, footer: str) -> None:
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Emu(0), Emu(0), Inches(0.18), _HEIGHT)
    bar.fill.solid()
    bar.fill.fore_color.rgb = _ACCENT
    bar.line.fill.background()
    bar.name = "Accent"
    box = slide.shapes.add_textbox(
        _MARGIN, Emu(_HEIGHT - Inches(0.55)), Emu(_WIDTH - 2 * _MARGIN), Inches(0.4)
    )
    box.name = "Footer"
    _paragraphs(box.text_frame, [f"{footer}    {number} / {total}"], size=11, colour=_MUTED)


def write_pptx(slides: Sequence[Slide], *, title: str, footer: str) -> bytes:
    deck = Presentation()
    deck.slide_width = _WIDTH
    deck.slide_height = _HEIGHT
    deck.core_properties.title = plain(title)[:255]
    deck.core_properties.author = "StudyPilot"
    blank = deck.slide_layouts[6]
    body_width = Emu(_WIDTH - 2 * _MARGIN)
    for number, outline in enumerate(slides, start=1):
        slide = deck.slides.add_slide(blank)
        _furniture(slide, number, len(slides), footer)
        if outline.kind == "title":
            box = slide.shapes.add_textbox(_MARGIN, Inches(2.4), body_width, Inches(1.8))
            box.name = "Title"
            _paragraphs(box.text_frame, [plain(outline.title)], size=40, bold=True, colour=_ACCENT)
            if outline.subtitle:
                sub = slide.shapes.add_textbox(_MARGIN, Inches(4.3), body_width, Inches(1.2))
                sub.name = "Subtitle"
                _paragraphs(sub.text_frame, [plain(outline.subtitle)], size=20, colour=_MUTED)
        else:
            head = slide.shapes.add_textbox(_MARGIN, Inches(0.45), body_width, Inches(1.0))
            head.name = "Title"
            _paragraphs(head.text_frame, [plain(outline.title)], size=30, bold=True, colour=_ACCENT)
            if outline.kind == "points":
                body = slide.shapes.add_textbox(_MARGIN, Inches(1.65), body_width, Inches(5.0))
                body.name = "Body"
                _paragraphs(body.text_frame, outline.points, size=22, bullet=True, space_after=14)
            else:
                panel = slide.shapes.add_shape(
                    MSO_SHAPE.RECTANGLE, _MARGIN, Inches(1.6), body_width, Inches(4.9)
                )
                panel.name = "Code"
                panel.fill.solid()
                panel.fill.fore_color.rgb = _CODE_BG
                panel.line.fill.background()
                frame = panel.text_frame
                frame.margin_left = frame.margin_right = Inches(0.3)
                frame.vertical_anchor = MSO_ANCHOR.TOP
                _paragraphs(
                    frame,
                    (outline.code or "").splitlines() or [" "],
                    size=15,
                    font="Consolas",
                    space_after=0,
                )
                for paragraph in frame.paragraphs:
                    paragraph.alignment = PP_ALIGN.LEFT
                if outline.caption:
                    cap = slide.shapes.add_textbox(_MARGIN, Inches(6.5), body_width, Inches(0.4))
                    cap.name = "Caption"
                    _paragraphs(cap.text_frame, [plain(outline.caption)], size=12, colour=_MUTED)
        notes_frame = slide.notes_slide.notes_text_frame if outline.notes else None
        if outline.notes and notes_frame is not None:
            notes_frame.text = outline.notes
    buffer = io.BytesIO()
    deck.save(buffer)
    return buffer.getvalue()


def render_lesson_slides(source: LessonSource) -> RenderedFile:
    outline = lesson_outline(source)
    footer = "StudyPilot - sample content" if source.lesson.is_synthetic else "StudyPilot"
    data = write_pptx(outline, title=source.lesson.content.title, footer=footer)
    return RenderedFile(
        data=data,
        content_type=PPTX_TYPE,
        file_name=file_name_for(source.lesson.content.title, "slides", "pptx"),
        page_count=len(outline),
        unsupported_characters=0,
    )


def render_roadmap_slides(source: RoadmapSource) -> RenderedFile:
    outline = roadmap_outline(source)
    footer = "StudyPilot - sample content" if source.roadmap.is_synthetic else "StudyPilot"
    data = write_pptx(outline, title=source.roadmap.title, footer=footer)
    return RenderedFile(
        data=data,
        content_type=PPTX_TYPE,
        file_name=file_name_for(source.roadmap.title, "slides", "pptx"),
        page_count=len(outline),
        unsupported_characters=0,
    )
