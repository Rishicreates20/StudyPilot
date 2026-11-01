"""Fonts for exported files, and an honest account of what they can show.

The PDF uses Noto Sans for Latin text with Noto Sans Devanagari and Noto Sans Oriya as fallbacks,
shaped by HarfBuzz, and Noto Sans Mono for code (see ``fonts/README.md`` for sources and licence).
No font is assumed to cover everything: before text is drawn, every character is checked against
the fonts' character maps, and one that no font covers is replaced with a visible replacement mark
and counted. The count is stored with the export, so a learner (and a developer) can see that
something could not be shown instead of getting silently missing letters.
"""

import unicodedata
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

from fontTools.ttLib import TTFont  # pyright: ignore[reportMissingTypeStubs]

FONT_DIR = Path(__file__).parent / "fonts"

# Family name -> {style: file}. "" is regular, "B" bold, "I" italic.
PDF_FONTS: dict[str, dict[str, str]] = {
    "NotoSans": {
        "": "NotoSans-Regular.ttf",
        "B": "NotoSans-Bold.ttf",
        "I": "NotoSans-Italic.ttf",
    },
    "NotoSansDevanagari": {
        "": "NotoSansDevanagari-Regular.ttf",
        "B": "NotoSansDevanagari-Bold.ttf",
    },
    "NotoSansOriya": {
        "": "NotoSansOriya-Regular.ttf",
        "B": "NotoSansOriya-Bold.ttf",
    },
    "NotoSansMono": {"": "NotoSansMono-Regular.ttf"},
}
BODY_FAMILY = "NotoSans"
MONO_FAMILY = "NotoSansMono"
FALLBACK_FAMILIES = ("NotoSansDevanagari", "NotoSansOriya")

# Shown where no font has a glyph. U+FFFD is in Noto Sans and Noto Sans Mono (checked by a test).
REPLACEMENT = "\ufffd"

# Characters that are never drawn but must survive (joiners control Indic conjuncts).
_INVISIBLE_OK = frozenset({"\u200c", "\u200d", "\n", "\t"})


@cache
def _coverage(file_name: str) -> frozenset[int]:
    font = TTFont(FONT_DIR / file_name, lazy=True)
    try:
        cmap: dict[int, str] | None = font.getBestCmap()
        return frozenset(cmap or {})
    finally:
        font.close()


def coverage(families: tuple[str, ...]) -> frozenset[int]:
    """Every code point the regular faces of ``families`` can show."""
    points: set[int] = set()
    for family in families:
        points |= _coverage(PDF_FONTS[family][""])
    return frozenset(points)


@dataclass
class TextGuard:
    """Replaces characters no font can show, and counts them across a whole document."""

    families: tuple[str, ...] = (BODY_FAMILY, *FALLBACK_FAMILIES)
    unsupported: int = 0
    _seen: set[str] = field(default_factory=set[str])

    def clean(self, text: str, *, families: tuple[str, ...] | None = None) -> str:
        """``text`` normalised to NFC, with uncovered characters replaced by ``REPLACEMENT``."""
        covered = coverage(families or self.families)
        out: list[str] = []
        for char in unicodedata.normalize("NFC", text):
            if char in _INVISIBLE_OK:
                out.append(char)
            elif unicodedata.category(char) in {"Cc", "Cf"}:
                # Other control and format characters (including bidi overrides, which can make
                # text display in a misleading order) are dropped, not counted.
                continue
            elif ord(char) in covered:
                out.append(char)
            else:
                self.unsupported += 1
                self._seen.add(char)
                out.append(REPLACEMENT)
        return "".join(out)

    def code(self, text: str) -> str:
        """Text for a code block, checked against the mono font (with the body fonts behind it)."""
        return self.clean(text, families=(MONO_FAMILY, *self.families))


def script_of(text: str) -> str:
    """The main script of ``text``: ``deva``, ``orya`` or ``latn`` (for slide font choices)."""
    counts = {"deva": 0, "orya": 0, "latn": 0}
    for char in text:
        point = ord(char)
        if 0x0900 <= point <= 0x097F or 0xA8E0 <= point <= 0xA8FF:
            counts["deva"] += 1
        elif 0x0B00 <= point <= 0x0B7F:
            counts["orya"] += 1
        elif char.isalpha():
            counts["latn"] += 1
    return max(counts, key=lambda key: counts[key]) if any(counts.values()) else "latn"
