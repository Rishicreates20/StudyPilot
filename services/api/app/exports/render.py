"""One entry point: render an export of a lesson or a roadmap in the format asked for."""

from app.exports.lesson_pdf import render_notes, render_revision
from app.exports.model import ExportFormat, LessonSource, RenderedFile, RoadmapSource
from app.exports.roadmap_pdf import render_roadmap
from app.exports.slides import render_lesson_slides, render_roadmap_slides


class UnsupportedExport(ValueError):
    """The format does not apply to this kind of source (the database refuses it too)."""


def render(export_format: ExportFormat, source: LessonSource | RoadmapSource) -> RenderedFile:
    """CPU-bound and synchronous: callers in async code run it in a thread."""
    if isinstance(source, LessonSource):
        if export_format == "notes_pdf":
            return render_notes(source)
        if export_format == "revision_pdf":
            return render_revision(source)
        if export_format == "slides_pptx":
            return render_lesson_slides(source)
    else:
        if export_format == "roadmap_pdf":
            return render_roadmap(source)
        if export_format == "slides_pptx":
            return render_roadmap_slides(source)
    raise UnsupportedExport(f"{export_format} cannot be made from this source")
