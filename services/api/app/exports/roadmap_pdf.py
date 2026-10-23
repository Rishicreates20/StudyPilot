"""A roadmap version as a PDF learning plan: overview, objectives, schedule, modules, extras."""

from app.exports.model import (
    PDF_TYPE,
    RenderedFile,
    RoadmapSource,
    file_name_for,
    language_name,
    long_date,
)
from app.exports.pdf_base import DocumentInfo, StudyDocument
from app.schemas.roadmaps import Roadmap, RoadmapItem

_BASIS = {
    "learner_stated": "What you told StudyPilot about your syllabus",
    "uploaded_document": "Your uploaded study material",
    "general_knowledge": "General knowledge of the subject (no syllabus was given)",
}


def _hours(minutes: int) -> str:
    hours, rest = divmod(minutes, 60)
    if not hours:
        return f"{rest} min"
    return f"{hours} h {rest} min" if rest else f"{hours} h"


def _module_of(roadmap: Roadmap) -> dict[str, str]:
    return {str(topic.id): module.title for module in roadmap.modules for topic in module.topics}


def _scheduled(roadmap: Roadmap) -> list[RoadmapItem]:
    """Every item with a study day, in day order (optional extras have none)."""
    items = [topic for module in roadmap.modules for topic in module.topics]
    items += roadmap.revision_sessions
    return sorted(
        (item for item in items if item.day_number is not None),
        key=lambda item: (item.day_number or 0, item.position),
    )


def render_roadmap(source: RoadmapSource) -> RenderedFile:
    roadmap = source.roadmap
    facts = [
        ("Goal", source.goal_title),
        ("Version", str(roadmap.version)),
        ("Topics", str(roadmap.topic_count)),
        ("Plan length", f"{roadmap.total_days} days, {_hours(roadmap.total_minutes)} in total"),
        ("Daily time", f"About {roadmap.daily_minutes} minutes"),
        ("Target date", long_date_or_none(roadmap)),
        ("Created", long_date(roadmap.created_at)),
        ("Language", language_name(roadmap.language)),
    ]
    pdf = StudyDocument(
        DocumentInfo(
            title=roadmap.title,
            subtitle=source.goal_title,
            kind_label="Learning roadmap",
            language=roadmap.language,
            facts=facts,
            is_sample=roadmap.is_synthetic,
        )
    )
    pdf.title_page()
    pdf.add_page()

    pdf.heading("Overview")
    pdf.paragraph(roadmap.overview)
    pdf.label_value("Where this takes you:", roadmap.target_outcome)
    pdf.label_value("Planned from:", _BASIS.get(roadmap.syllabus_basis, roadmap.syllabus_basis))

    pdf.heading("Learning objectives")
    pdf.bullets([f"{o.id.upper()}  {o.text}" for o in roadmap.objectives])

    module_of = _module_of(roadmap)
    schedule = _scheduled(roadmap)
    if schedule:
        pdf.heading("Schedule at a glance")
        pdf.data_table(
            ("Day", "What to study", "Module", "Time"),
            [
                (
                    str(item.day_number),
                    item.title if item.kind == "topic" else f"Revision: {item.title}",
                    module_of.get(str(item.id), "-"),
                    f"{item.estimated_minutes} min",
                )
                for item in schedule
            ],
            widths=(9, 49, 30, 12),
            size=8.5,
        )

    for module in roadmap.modules:
        pdf.heading(f"Module {module.position}: {module.title}")
        pdf.paragraph(module.summary, muted=True)
        for topic in module.topics:
            day = f"Day {topic.day_number} - " if topic.day_number is not None else ""
            pdf.heading(f"{topic.title}", level=3)
            pdf.paragraph(
                f"{day}about {topic.estimated_minutes} minutes"
                + (
                    f" - objectives {', '.join(topic.objective_ids).upper()}"
                    if topic.objective_ids
                    else ""
                ),
                size=9,
                muted=True,
            )
            pdf.paragraph(topic.description)
            if topic.practice_task:
                pdf.label_value("Practice:", topic.practice_task)

    if roadmap.revision_sessions:
        pdf.heading("Revision sessions")
        for item in roadmap.revision_sessions:
            day = f" (day {item.day_number})" if item.day_number is not None else ""
            pdf.label_value(f"{item.title}{day}:", item.description)

    if roadmap.enrichment:
        pdf.heading("Optional extras")
        pdf.paragraph("Not part of the schedule: for when you have time to spare.", muted=True)
        for item in roadmap.enrichment:
            pdf.label_value(f"{item.title}:", item.description)

    if roadmap.assumptions or roadmap.unknowns:
        pdf.heading("Check these yourself")
        pdf.paragraph(
            "The plan was made with these assumptions and open questions. If one is wrong, "
            "revise the roadmap in StudyPilot.",
            muted=True,
        )
        if roadmap.assumptions:
            pdf.heading("Assumptions", level=3)
            pdf.bullets(roadmap.assumptions)
        if roadmap.unknowns:
            pdf.heading("Open questions", level=3)
            pdf.bullets(roadmap.unknowns)

    data = pdf.render()
    return RenderedFile(
        data=data,
        content_type=PDF_TYPE,
        file_name=file_name_for(roadmap.title, "roadmap", "pdf"),
        page_count=pdf.pages_count,
        unsupported_characters=pdf.guard.unsupported,
    )


def long_date_or_none(roadmap: Roadmap) -> str:
    target = roadmap.target_date
    return f"{target.day} {target:%B %Y}" if target else "None set"
