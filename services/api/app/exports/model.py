"""What the renderers take and give back. Pure data: no database, no storage, no network."""

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app.schemas.lessons import LessonDetail
from app.schemas.roadmaps import Roadmap

ExportFormat = Literal["notes_pdf", "revision_pdf", "roadmap_pdf", "slides_pptx"]
LESSON_FORMATS: tuple[ExportFormat, ...] = ("notes_pdf", "revision_pdf", "slides_pptx")
ROADMAP_FORMATS: tuple[ExportFormat, ...] = ("roadmap_pdf", "slides_pptx")

PDF_TYPE = "application/pdf"
PPTX_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation"

# Bump when a layout changes: the database keeps one export per source, format and template
# version, so a new version makes new files instead of serving the old layout again.
TEMPLATE_VERSION = "2026-10.v1"

LANGUAGE_NAMES = {"en": "English", "hi": "Hindi", "or": "Odia"}


@dataclass(frozen=True)
class LessonSource:
    lesson: LessonDetail
    topic_title: str
    goal_title: str


@dataclass(frozen=True)
class RoadmapSource:
    roadmap: Roadmap
    goal_title: str


@dataclass(frozen=True)
class RenderedFile:
    data: bytes
    content_type: str
    file_name: str
    # Pages of a PDF, or slides of a presentation.
    page_count: int
    # Characters no embedded font could show; each was printed as a replacement mark.
    unsupported_characters: int


def file_name_for(title: str, suffix: str, extension: str) -> str:
    """A download name made of ASCII letters, digits and ``-``: safe in a header and a path.

    Matches the database's rule ``^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$``. Titles in Hindi or Odia
    have no ASCII letters, so they fall back to ``studypilot-<suffix>``.
    """
    ascii_title = (
        unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii").lower()
    )
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_title).strip("-")[:60].strip("-")
    stem = f"{slug}-{suffix}" if slug else f"studypilot-{suffix}"
    return f"{stem}.{extension}"


def long_date(value: datetime) -> str:
    return f"{value.day} {value:%B %Y}"


def language_name(code: str) -> str:
    return LANGUAGE_NAMES.get(code, code)
