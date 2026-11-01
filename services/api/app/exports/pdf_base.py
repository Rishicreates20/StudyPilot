"""The shared PDF template: page furniture, headings, text, lists, tables, code and callouts.

Every exported PDF is built from these few pieces so they look like one family: A4, Noto fonts
(Latin, Devanagari and Odia, shaped by HarfBuzz), a title page, headings that also become PDF
bookmarks, a running header from page two, and "Page X of Y" in the footer. Nothing here reads
the database or knows what a lesson is.

All text goes through ``TextGuard`` first, so a character no font covers becomes a visible
replacement mark and is counted, never a silently missing letter. Learner and model text is
drawn as plain text: there is no markup, no HTML and no link in it.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from fpdf import FPDF
from fpdf.enums import Align, TableBordersLayout, XPos, YPos
from fpdf.fonts import FontFace

from app.exports.typography import (
    BODY_FAMILY,
    FALLBACK_FAMILIES,
    FONT_DIR,
    MONO_FAMILY,
    PDF_FONTS,
    TextGuard,
)

# Colours (RGB). One accent, the rest neutral, all dark enough on white for print and screens.
INK = (33, 37, 41)
MUTED = (96, 103, 112)
ACCENT = (52, 64, 156)
RULE = (206, 212, 218)
CODE_BG = (243, 244, 246)
CALLOUT = {
    "tip": ((232, 245, 233), (46, 125, 50), "Tip"),
    "note": ((232, 240, 254), (52, 64, 156), "Note"),
    "warning": ((255, 243, 224), (183, 92, 0), "Watch out"),
}

BODY_SIZE = 10.5
LINE = 5.6  # line height in mm for body text
MARGIN = 18


@dataclass(frozen=True)
class DocumentInfo:
    title: str
    # Shown under the title on the title page and in the running header.
    subtitle: str
    kind_label: str  # "Study notes", "Revision sheet", "Learning roadmap"
    language: str  # BCP-47 primary tag of the content, e.g. "en", "hi", "or"
    # Facts for the title page, e.g. [("Version", "2"), ("Created", "12 October 2026")].
    facts: Sequence[tuple[str, str]] = ()
    # True when a test double wrote the content: every page says so.
    is_sample: bool = False


class StudyDocument(FPDF):
    """An FPDF with StudyPilot's fonts, page furniture and building blocks."""

    def __init__(self, info: DocumentInfo, guard: TextGuard | None = None) -> None:
        super().__init__(orientation="portrait", unit="mm", format="A4")
        self.info = info
        self.guard = guard or TextGuard()
        self._outline_level = -1
        for family, styles in PDF_FONTS.items():
            for style, file_name in styles.items():
                self.add_font(family, style, FONT_DIR / file_name)
        self.set_fallback_fonts(list(FALLBACK_FAMILIES), exact_match=False)
        self.set_text_shaping(True)
        self.set_margins(MARGIN, MARGIN + 4, MARGIN)
        self.set_auto_page_break(auto=True, margin=MARGIN + 2)
        self.set_title(self.guard.clean(info.title))
        self.set_subject(info.kind_label)
        self.set_author("StudyPilot")
        self.set_creator("StudyPilot exporter")
        self.set_lang(info.language)
        self.set_text_color(*INK)

    # --- Page furniture ---------------------------------------------------------------------

    def header(self) -> None:
        if self.page_no() == 1:
            return
        self.set_y(9)
        self.set_font(BODY_FAMILY, "", 8)
        self.set_text_color(*MUTED)
        # Each part is placed explicitly: after a shaped (Hindi or Odia) cell the cursor is not
        # a reliable starting point for the next one.
        self.set_xy(self.l_margin, 9)
        self.cell(self.epw, 5, self.info.kind_label, align=Align.R)
        width = self.epw * 0.7
        self.set_xy(self.l_margin, 9)
        self.cell(width, 5, self._fit(self.guard.clean(self.info.title), width))
        self.set_xy(self.l_margin, 14)
        self.set_draw_color(*RULE)
        self.line(self.l_margin, self.get_y() + 1, self.w - self.r_margin, self.get_y() + 1)
        self.set_y(MARGIN + 4)
        self.set_text_color(*INK)

    def footer(self) -> None:
        self.set_y(-13)
        self.set_font(BODY_FAMILY, "", 8)
        self.set_text_color(*MUTED)
        left = (
            "Sample content from the test provider - not real study material"
            if (self.info.is_sample)
            else "StudyPilot"
        )
        self.cell(self.epw, 5, f"Page {self.page_no()} of {{nb}}", align=Align.R)
        self.set_x(self.l_margin)
        self.cell(self.epw * 0.75, 5, left)
        self.set_text_color(*INK)

    def _fit(self, text: str, width: float) -> str:
        """``text`` shortened with an ellipsis to fit ``width`` in the current font."""
        if self.get_string_width(text) <= width:
            return text
        while text and self.get_string_width(text + "...") > width:
            text = text[:-1]
        return text.rstrip() + "..."

    # --- Title page ----------------------------------------------------------------------------

    def title_page(self) -> None:
        self.add_page()
        self.set_y(60)
        self.set_font(BODY_FAMILY, "", 11)
        self.set_text_color(*ACCENT)
        self.cell(0, 6, self.info.kind_label.upper(), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(3)
        self.set_text_color(*INK)
        self.set_font(BODY_FAMILY, "B", 24)
        self.multi_cell(
            0,
            11,
            self.guard.clean(self.info.title),
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
            align=Align.L,
        )
        if self.info.subtitle:
            self.ln(2)
            self.set_font(BODY_FAMILY, "", 13)
            self.set_text_color(*MUTED)
            self.multi_cell(
                0,
                7,
                self.guard.clean(self.info.subtitle),
                new_x=XPos.LMARGIN,
                new_y=YPos.NEXT,
                align=Align.L,
            )
        self.ln(8)
        self.set_draw_color(*ACCENT)
        self.set_line_width(0.8)
        self.line(self.l_margin, self.get_y(), self.l_margin + 30, self.get_y())
        self.set_line_width(0.2)
        self.ln(8)
        self.set_font(BODY_FAMILY, "", 10)
        for label, value in self.info.facts:
            self.set_text_color(*MUTED)
            self.cell(40, 6.5, label, new_x=XPos.RIGHT, new_y=YPos.TOP)
            self.set_text_color(*INK)
            self.multi_cell(
                0, 6.5, self.guard.clean(value), new_x=XPos.LMARGIN, new_y=YPos.NEXT, align=Align.L
            )
        if self.info.is_sample:
            self.ln(8)
            self.callout(
                "warning",
                "This file was made from sample content written by StudyPilot's built-in test "
                "provider. It is not real study material.",
                title="Sample content",
            )
        self.set_text_color(*INK)

    # --- Text ------------------------------------------------------------------------------------

    def _room(self, needed: float) -> None:
        """Start a new page unless ``needed`` mm fit above the bottom margin."""
        if self.get_y() + needed > self.page_break_trigger:
            self.add_page()

    def heading(self, text: str, level: int = 1) -> None:
        """A heading that is never left alone at the bottom of a page, and becomes a bookmark."""
        size, gap_before, gap_after = {1: (16, 6, 3), 2: (13, 5, 2), 3: (11, 3, 1.5)}[level]
        clean = self.guard.clean(text)
        if self.get_y() > self.t_margin + 1:
            self.ln(gap_before)
        self._room(size * 0.6 + 3 * LINE)
        # Bookmarks may not skip a level (a level-3 heading straight after a level-1 one).
        outline_level = min(level - 1, self._outline_level + 1)
        self._outline_level = outline_level
        self.start_section(clean, level=outline_level)
        self.set_font(BODY_FAMILY, "B", size)
        self.set_text_color(*(ACCENT if level == 1 else INK))
        self.multi_cell(0, size * 0.5, clean, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align=Align.L)
        self.set_text_color(*INK)
        if level == 1:
            self.set_draw_color(*RULE)
            self.line(self.l_margin, self.get_y() + 1, self.w - self.r_margin, self.get_y() + 1)
            self.ln(2)
        self.ln(gap_after)

    def paragraph(self, text: str, *, size: float = BODY_SIZE, muted: bool = False) -> None:
        self.set_font(BODY_FAMILY, "", size)
        if muted:
            self.set_text_color(*MUTED)
        self.multi_cell(
            0,
            LINE * size / BODY_SIZE,
            self.guard.clean(text),
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
            align=Align.L,
        )
        self.set_text_color(*INK)
        self.ln(1.8)

    def label_value(self, label: str, text: str) -> None:
        """A short bold label followed by text, e.g. "Answer: ...", wrapped as one paragraph."""
        self.set_font(BODY_FAMILY, "B", BODY_SIZE)
        self.write(LINE, self.guard.clean(label) + " ")
        self.set_font(BODY_FAMILY, "", BODY_SIZE)
        self.write(LINE, self.guard.clean(text))
        self.ln(LINE)
        self.ln(1.5)

    def bullets(
        self, items: Sequence[str], *, ordered: bool = False, size: float = BODY_SIZE
    ) -> None:
        """A list with a hanging indent, numbered or bulleted."""
        indent = 7
        line = LINE * size / BODY_SIZE
        for number, item in enumerate(items, start=1):
            self._room(line * 1.5)
            self.set_font(BODY_FAMILY, "", size)
            marker = f"{number}." if ordered else "•"
            self.set_x(self.l_margin + 1.5)
            self.cell(indent - 1.5, line, marker, new_x=XPos.RIGHT, new_y=YPos.TOP)
            self.multi_cell(
                self.epw - indent,
                line,
                self.guard.clean(item),
                new_x=XPos.LMARGIN,
                new_y=YPos.NEXT,
                align=Align.L,
            )
            self.ln(0.8)
        self.ln(1.5)

    def code(self, code: str, *, caption: str | None = None, language: str | None = None) -> None:
        """A code block: monospaced, on a tinted background, long lines wrapped, nothing styled."""
        label = " - ".join(part for part in (language, caption) if part)
        if label:
            self.set_font(BODY_FAMILY, "I", 8.5)
            self.set_text_color(*MUTED)
            self.multi_cell(
                0, 4.5, self.guard.clean(label), new_x=XPos.LMARGIN, new_y=YPos.NEXT, align=Align.L
            )
            self.set_text_color(*INK)
        self.set_font(MONO_FAMILY, "", 8.5)
        self.set_fill_color(*CODE_BG)
        text = self.guard.code(code.expandtabs(4).rstrip("\n"))
        self.multi_cell(
            0,
            4.4,
            text,
            fill=True,
            padding=(3, 3, 3, 3),
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
            align=Align.L,
        )
        self.ln(3)

    def callout(self, kind: str, text: str, *, title: str | None = None) -> None:
        """A tinted box with a coloured label: a tip, a note or a warning."""
        background, colour, default_title = CALLOUT.get(kind, CALLOUT["note"])
        self._room(4 * LINE)
        self.set_fill_color(*background)
        self.set_font(BODY_FAMILY, "B", 9.5)
        self.set_text_color(*colour)
        self.multi_cell(
            0,
            5,
            self.guard.clean(title or default_title),
            fill=True,
            padding=(3, 3, 1, 3),
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
            align=Align.L,
        )
        self.set_text_color(*INK)
        self.set_font(BODY_FAMILY, "", 9.5)
        self.multi_cell(
            0,
            5,
            self.guard.clean(text),
            fill=True,
            padding=(1, 3, 3, 3),
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
            align=Align.L,
        )
        self.ln(3)

    def data_table(
        self,
        header: Sequence[str],
        rows: Sequence[Sequence[str]],
        *,
        widths: Sequence[float],
        size: float = 9,
    ) -> None:
        """A table with a repeated header row; cells wrap, rows never split across pages."""
        self.set_font(BODY_FAMILY, "", size)
        head_style = FontFace(emphasis="BOLD", color=INK, fill_color=CODE_BG)
        with super().table(
            col_widths=tuple(widths),
            width=self.epw,
            line_height=size * 0.55,
            headings_style=head_style,
            borders_layout=TableBordersLayout.HORIZONTAL_LINES,
            padding=1.6,
            repeat_headings=1,
            text_align="LEFT",
        ) as table:
            table.row([self.guard.clean(cell) for cell in header])
            for row in rows:
                table.row([self.guard.clean(cell) for cell in row])
        self.ln(3)

    def render(self) -> bytes:
        return bytes(self.output())
