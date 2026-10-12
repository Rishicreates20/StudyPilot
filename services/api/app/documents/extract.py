"""Getting text, with page boundaries, out of an uploaded file.

Nothing here runs the file: PDFs are read with ``pypdf`` (pure Python, no rendering, no scripts
executed, no external programs) and everything else is plain text. The limits come from
configuration and are enforced here (pages, characters), so a hostile file is refused with a clear
reason instead of being allowed to run the worker out of memory or time.

Pages that have no text layer (a scanned PDF, a photographed page) are not read here: they are
flagged ``needs_ocr`` and the worker decides whether a vision model reads them. Every oddity
(a page that would not parse, text that had to be repaired) becomes a warning that is kept with the
document and shown to the learner.
"""

import io
import math
import re
from dataclasses import dataclass, field
from typing import Literal

from pypdf import PdfReader, PdfWriter

from app.documents.sniff import decode_text

PageSource = Literal["text_layer", "ocr", "text"]

# A PDF page with less text than this has no usable text layer (a scan, or an image page).
MIN_TEXT_LAYER_CHARS = 20
# Plain text and pasted material are cut into parts about this long (at paragraph boundaries) so
# they can be previewed, reviewed and cited by part number like the pages of a PDF.
PART_TARGET_CHARS = 4000

# Lecture notes repeat a running header or footer on every page ("KIIT POLYTECHNIC", "Database
# Management System 18 Author"). It is not content: left in, it pads every passage and is mistaken
# for a heading. A line near the top or bottom of a page whose shape (digits ignored) recurs on at
# least this share of the pages, and on at least MIN_PAGES_FOR_FURNITURE of them, is removed.
FURNITURE_SHARE = 0.4
MIN_PAGES_FOR_FURNITURE = 4
_EDGE_LINES = 3
_MAX_FURNITURE_CHARS = 90

# Bullets and arrows typed in the Symbol and Wingdings fonts reach the text as invisible
# private-use characters. The common ones become the plain characters they stood for; any other
# private-use character is dropped.
_SYMBOL_FONT_CHARS = {
    "\uf0b7": "\u2022",  # Symbol bullet
    "\uf0a7": "\u2022",
    "\uf0d8": "\u2022",  # Wingdings arrow-head bullet
    "\uf076": "\u2022",  # Wingdings diamond bullet
    "\uf0fc": "\u2713",  # Wingdings check mark
    "\uf0e0": "\u2192",  # Wingdings arrow
    "\uf0ae": "\u2192",  # Symbol arrow
    "\uf020": " ",
}
_PRIVATE_USE = re.compile("[\ue000-\uf8ff]")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f￾￿]")
_TRAILING_SPACE = re.compile(r"[ \t]+\n")
_BLANK_RUNS = re.compile(r"\n{3,}")
_SENTENCE_END = re.compile(r"(?<=[.!?।])\s+")


class ExtractionFailed(Exception):
    """The file cannot be read. ``code`` is stable and ``message`` is safe to show a learner."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


@dataclass(frozen=True)
class ExtractedPage:
    number: int
    text: str
    source: PageSource
    # Only for pages read by a vision model: how sure it was.
    legibility: str | None = None
    # A PDF page without a text layer that a vision model may be asked to read.
    needs_ocr: bool = False


@dataclass(frozen=True)
class Warn:
    code: str
    message: str
    page: int | None = None


@dataclass
class Extraction:
    pages: list[ExtractedPage]
    # Real pages (a PDF or an image) or parts (text): decides how a position is described.
    paginated: bool
    page_count: int
    warnings: list[Warn] = field(default_factory=lambda: [])


def _symbol_font_char(match: re.Match[str]) -> str:
    return _SYMBOL_FONT_CHARS.get(match.group(0), "")


def clean_text(text: str) -> str:
    """Line endings unified, control characters dropped, runs of blank lines and spaces tidied."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ")
    text = _PRIVATE_USE.sub(_symbol_font_char, text)
    text = _CONTROL.sub("", text)
    text = _TRAILING_SPACE.sub("\n", text)
    return _BLANK_RUNS.sub("\n\n", text).strip()


_DIGITS = re.compile(r"\d{1,6}")


def _shape(line: str) -> str:
    """A line with its numbers and spacing ignored, to recognise a running header or footer."""
    return re.sub(r"\d+", "#", " ".join(line.split())).casefold()


def _numbers(line: str) -> tuple[int, ...]:
    return tuple(int(token) for token in _DIGITS.findall(line))


def _edge_positions(lines: list[str]) -> list[int]:
    """Indexes of the first and last few non-empty lines of a page."""
    filled = [i for i, line in enumerate(lines) if line.strip()]
    return sorted({*filled[:_EDGE_LINES], *filled[-_EDGE_LINES:]})


def _is_running(occurrences: list[tuple[int, tuple[int, ...]]]) -> bool:
    """Whether a recurring line is furniture: each number in it is either the same on every page
    (``of 9``) or moves with the page (a page number, at a fixed offset from the page's place).
    A line whose numbers wander (``Question 3``, ``Unit 2``) is content that happens to repeat."""
    for position in range(len(occurrences[0][1])):
        values = {numbers[position] for _, numbers in occurrences}
        offsets = {numbers[position] - index for index, numbers in occurrences}
        if len(values) > 1 and len(offsets) > 1:
            return False
    return True


def strip_page_furniture(texts: list[str]) -> list[str]:
    """The pages' text without the header and footer lines that repeat page after page."""
    if len(texts) < MIN_PAGES_FOR_FURNITURE:
        return texts
    split = [text.split("\n") for text in texts]
    seen: dict[str, list[tuple[int, tuple[int, ...]]]] = {}
    for index, lines in enumerate(split):
        for i in _edge_positions(lines):
            line = lines[i]
            if len(line.strip()) <= _MAX_FURNITURE_CHARS:
                seen.setdefault(_shape(line), []).append((index, _numbers(line)))
    needed = max(MIN_PAGES_FOR_FURNITURE, math.ceil(FURNITURE_SHARE * len(texts)))
    furniture = {
        shape
        for shape, occurrences in seen.items()
        if shape.strip("# ")
        and len({index for index, _ in occurrences}) >= needed
        and _is_running(occurrences)
    }
    if not furniture:
        return texts
    cleaned: list[str] = []
    for lines in split:
        drop = {i for i in _edge_positions(lines) if _shape(lines[i]) in furniture}
        kept = [line for i, line in enumerate(lines) if i not in drop]
        cleaned.append(clean_text("\n".join(kept)))
    return cleaned


def split_into_parts(text: str, target: int = PART_TARGET_CHARS) -> list[str]:
    """``text`` cut into parts of about ``target`` characters, at paragraph breaks first."""
    parts: list[str] = []
    current: list[str] = []
    size = 0
    for paragraph in (p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()):
        pieces = [paragraph] if len(paragraph) <= target else _split_long(paragraph, target)
        for piece in pieces:
            if current and size + len(piece) + 2 > target:
                parts.append("\n\n".join(current))
                current, size = [], 0
            current.append(piece)
            size += len(piece) + 2
    if current:
        parts.append("\n\n".join(current))
    return parts


def _split_long(paragraph: str, target: int) -> list[str]:
    """A paragraph longer than ``target`` cut at sentence ends, and at words if it has none."""
    pieces: list[str] = []
    current = ""
    for sentence in _SENTENCE_END.split(paragraph):
        while len(sentence) > target:
            cut = sentence.rfind(" ", 0, target)
            cut = cut if cut > target // 2 else target
            if current:
                pieces.append(current)
                current = ""
            pieces.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if current and len(current) + len(sentence) + 1 > target:
            pieces.append(current)
            current = ""
        current = f"{current} {sentence}".strip()
    if current:
        pieces.append(current)
    return [piece for piece in pieces if piece]


def extract_plain(text: str, *, max_chars: int, source: Literal["text"] = "text") -> Extraction:
    """Plain or pasted text as parts. Fails if it is empty or longer than ``max_chars``."""
    cleaned = clean_text(text)
    if not cleaned:
        raise ExtractionFailed("DOCUMENT_EMPTY", "There is no text in that material.")
    if len(cleaned) > max_chars:
        raise ExtractionFailed(
            "DOCUMENT_TOO_LARGE",
            f"That text is longer than the limit of {max_chars:,} characters. "
            "Split it into several documents.",
        )
    parts = split_into_parts(cleaned)
    pages = [
        ExtractedPage(number=number, text=part, source=source)
        for number, part in enumerate(parts, start=1)
    ]
    return Extraction(pages=pages, paginated=False, page_count=len(pages))


def extract_text_file(data: bytes, *, max_chars: int) -> Extraction:
    text = decode_text(data)
    if text is None:
        raise ExtractionFailed(
            "FILE_TYPE_UNSUPPORTED", "That file's text could not be read. Save it as UTF-8."
        )
    return extract_plain(text, max_chars=max_chars)


def extract_pdf(data: bytes, *, max_pages: int, max_chars: int) -> Extraction:
    """The text layer of every page of a PDF, with the pages that have none flagged for OCR."""
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted and not reader.decrypt(""):
            raise ExtractionFailed(
                "PDF_ENCRYPTED",
                "This PDF is password-protected. Remove the password and upload it again.",
            )
        count = len(reader.pages)
    except ExtractionFailed:
        raise
    except Exception:
        raise ExtractionFailed(
            "DOCUMENT_UNREADABLE",
            "This PDF could not be opened. It may be damaged; try saving or exporting it again.",
        ) from None
    if count == 0:
        raise ExtractionFailed("DOCUMENT_EMPTY", "This PDF has no pages.")
    if count > max_pages:
        raise ExtractionFailed(
            "PDF_TOO_LONG",
            f"This PDF has {count} pages and the limit is {max_pages}. Upload it in parts.",
        )

    texts: list[str] = []
    warnings: list[Warn] = []
    total = 0
    for index in range(count):
        number = index + 1
        try:
            raw = reader.pages[index].extract_text() or ""
        except Exception:
            raw = ""
            warnings.append(
                Warn(
                    "PAGE_UNREADABLE", f"Page {number} could not be read and was left out.", number
                )
            )
        text = clean_text(raw)
        total += len(text)
        if total > max_chars:
            raise ExtractionFailed(
                "DOCUMENT_TOO_LARGE",
                f"This PDF has more text than the limit of {max_chars:,} characters. "
                "Upload it in parts.",
            )
        texts.append(text)

    pages = [
        ExtractedPage(
            number=number,
            text=text,
            source="text_layer",
            needs_ocr=len(text) < MIN_TEXT_LAYER_CHARS,
        )
        for number, text in enumerate(strip_page_furniture(texts), start=1)
    ]

    blank = [page.number for page in pages if page.needs_ocr]
    if blank and len(blank) < len(pages):
        shown = ", ".join(str(n) for n in blank[:10]) + (" and more" if len(blank) > 10 else "")
        message = (
            f"Page {shown} has no text layer (a scan or an image)."
            if len(blank) == 1
            else f"Pages {shown} have no text layer (scans or images)."
        )
        warnings.append(Warn("PAGES_WITHOUT_TEXT", message, blank[0]))
    return Extraction(pages=pages, paginated=True, page_count=count, warnings=warnings)


def single_page_pdf(data: bytes, number: int) -> bytes:
    """Page ``number`` (1-based) of a PDF as a PDF of its own, for a vision model to read."""
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            reader.decrypt("")
        writer = PdfWriter()
        writer.add_page(reader.pages[number - 1])
        buffer = io.BytesIO()
        writer.write(buffer)
        return buffer.getvalue()
    except Exception:
        raise ExtractionFailed(
            "DOCUMENT_UNREADABLE", f"Page {number} could not be prepared for reading."
        ) from None
