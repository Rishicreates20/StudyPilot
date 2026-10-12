"""Cutting a document into passages that can be found, read and cited on their own.

A passage is about ``target`` characters long and:

* **keeps its place**: the first and last page (or part) it draws on, and the heading in effect
  where it starts, so a citation can say "page 4, under *Borrowing rules*";
* **keeps its sense**: it breaks at paragraph boundaries, then at sentence ends, and only at a
  space inside a sentence that is longer than a whole passage; a heading goes with the text it
  introduces rather than ending a passage;
* **keeps its context**: each passage begins with the last ``overlap`` characters of the one
  before (cut at a word), so an idea that straddles a boundary is whole in at least one passage.

It is a pure function of the text: the same pages always give the same passages, so re-indexing
a document does not change what a stored citation points to unless the text itself changed.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

# A passage shorter than this at the end of a document is folded into the one before it.
MIN_TAIL_CHARS = 200
# A heading starts a new passage once the current one is at least this share of the target.
_HEADING_BREAK_SHARE = 0.4
_MAX_HEADING_CHARS = 90
_MAX_STANDALONE_WORDS = 10
_SENTENCE_END = re.compile(r"(?<=[.!?।])\s+")
_NUMBERED_HEADING = re.compile(r"^(?:\d+(?:\.\d+)+|\d+[.)]|[IVXLC]+[.)]|[A-Z][.)])\s+\S")
_MARKDOWN_HEADING = re.compile(r"^#{1,6}\s+(\S.*)$")
_SIMPLE_NUMBER = re.compile(r"^(?:\d+[.)]|[IVXLC]+[.)]|[A-Z][.)])\s")
_MAX_NUMBERED_ITEM_WORDS = 8
_SENTENCE_PUNCTUATION = re.compile(r"[:;,]\s|\.\s+\S")
_MAX_EMBEDDING_CHARS = 6000


@dataclass(frozen=True)
class Chunk:
    index: int
    page_start: int
    page_end: int
    section_title: str | None
    text: str


@dataclass(frozen=True)
class _Block:
    page: int
    text: str
    heading: bool


def is_heading(line: str, *, standalone: bool = False) -> str | None:
    """The heading text if ``line`` looks like a heading, else None.

    A line is a heading if it is Markdown (``# Title``), numbered (``2.1 Rules``), written in
    capitals, or, when it stands alone as a short paragraph without closing punctuation, a title.
    """
    stripped = line.strip()
    if not stripped or len(stripped) > _MAX_HEADING_CHARS:
        return None
    markdown = _MARKDOWN_HEADING.match(stripped)
    if markdown:
        return markdown.group(1).strip()
    numbered = _NUMBERED_HEADING.match(stripped) is not None
    if stripped.endswith((".", ",", ";", ":", "?", "!")) and not numbered:
        return None
    words = stripped.split()
    letters = [c for c in stripped if c.isalpha()]
    if not letters or len(words) > 12:
        return None
    if numbered:
        # "2.1 Rules" is a heading. "1. Reduction of redundancy: unlike a file system, ..." is a
        # list item: a simple number followed by a long or punctuated sentence is not.
        simple = _SIMPLE_NUMBER.match(stripped)
        if simple and (
            len(words) > _MAX_NUMBERED_ITEM_WORDS
            or _SENTENCE_PUNCTUATION.search(stripped[simple.end() :])
        ):
            return None
        return stripped
    if len(letters) >= 3 and all(c.isupper() for c in letters):
        return stripped
    if standalone and len(words) <= _MAX_STANDALONE_WORDS and stripped[0].isupper():
        return stripped
    return None


def _blocks(pages: Sequence[tuple[int, str]]) -> list[_Block]:
    blocks: list[_Block] = []
    for page, text in pages:
        for paragraph in re.split(r"\n\s*\n", text):
            lines = [line.strip() for line in paragraph.split("\n") if line.strip()]
            body: list[str] = []
            for line in lines:
                heading = is_heading(line, standalone=len(lines) == 1)
                if heading is None:
                    body.append(line)
                    continue
                if body:
                    blocks.append(_Block(page, " ".join(body), False))
                    body = []
                blocks.append(_Block(page, heading, True))
            if body:
                blocks.append(_Block(page, " ".join(body), False))
    return blocks


def _split_oversize(block: _Block, limit: int) -> list[_Block]:
    """A paragraph longer than ``limit``, cut at sentence ends (and at spaces if it must)."""
    if block.heading or len(block.text) <= limit:
        return [block]
    pieces: list[str] = []
    current = ""
    for sentence in _SENTENCE_END.split(block.text):
        while len(sentence) > limit:
            cut = sentence.rfind(" ", 0, limit)
            cut = cut if cut > limit // 2 else limit
            if current:
                pieces.append(current)
                current = ""
            pieces.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if current and len(current) + len(sentence) + 1 > limit:
            pieces.append(current)
            current = ""
        current = f"{current} {sentence}".strip()
    if current:
        pieces.append(current)
    return [_Block(block.page, piece, False) for piece in pieces if piece]


def _tail(text: str, overlap: int) -> str:
    """The last ``overlap`` characters of ``text``, starting at a word."""
    if overlap <= 0 or len(text) <= overlap:
        return ""
    tail = text[-overlap:]
    space = tail.find(" ")
    return tail[space + 1 :].strip() if space != -1 else ""


def chunk_pages(pages: Sequence[tuple[int, str]], *, target: int, overlap: int) -> list[Chunk]:
    """Passages for ``pages`` (``(page number, text)`` in order)."""
    items: list[_Block] = []
    for block in _blocks(pages):
        items.extend(_split_oversize(block, target))

    chunks: list[Chunk] = []
    new: list[_Block] = []  # what the passage being built adds (headings included)
    lead: _Block | None = None  # the overlap carried over from the previous passage
    section: str | None = None  # the heading in effect now
    start_section: str | None = None  # the heading in effect where the passage being built starts

    def size() -> int:
        return sum(len(b.text) + 2 for b in new) + (len(lead.text) + 2 if lead else 0)

    def emit() -> None:
        nonlocal new, lead
        blocks = ([lead] if lead else []) + new
        text = "\n\n".join(block.text for block in blocks)
        chunks.append(
            Chunk(
                index=len(chunks),
                page_start=blocks[0].page,
                page_end=blocks[-1].page,
                section_title=start_section,
                text=text,
            )
        )
        tail = _tail(text, overlap)
        lead = _Block(blocks[-1].page, tail, False) if tail else None
        new = []

    for block in items:
        dangling: list[_Block] = []
        if block.heading:
            section = block.text
            if new and size() >= target * _HEADING_BREAK_SHARE:
                emit()
        elif new and size() + len(block.text) + 2 > target:
            # A heading is never left at the end of a passage: it moves on with its text.
            while len(new) > 1 and new[-1].heading:
                dangling.insert(0, new.pop())
            emit()
            new = dangling
            if dangling:
                start_section = section
        if not new:
            start_section = section
        new.append(block)

    if new:
        emit()

    # Fold a tiny last passage into the one before it so the end of a document is not an orphan.
    if len(chunks) >= 2 and len(chunks[-1].text) < MIN_TAIL_CHARS:
        last, previous = chunks[-1], chunks[-2]
        chunks[-2:] = [
            Chunk(
                index=previous.index,
                page_start=previous.page_start,
                page_end=max(previous.page_end, last.page_end),
                section_title=previous.section_title,
                text=f"{previous.text}\n\n{last.text}",
            )
        ]
    return chunks


def embedding_input(document_title: str, chunk: Chunk) -> str:
    """What is embedded for a passage: its title and heading give a short passage its context."""
    head = f"{document_title}\n"
    if chunk.section_title:
        head += f"{chunk.section_title}\n"
    return (head + chunk.text)[:_MAX_EMBEDDING_CHARS]
