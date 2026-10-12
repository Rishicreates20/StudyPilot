"""Page numbers in a topic's text stay on the roadmap; the lesson writer never sees them."""

import uuid

import pytest

from app.ai.lesson.context import TopicFacts, build_context, without_page_references
from app.jobs.lesson_evidence import topic_query
from app.schemas.goals import Goal


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Keys and normal forms (Pages 30-39)", "Keys and normal forms"),
        ("SQL commands (Pages 42-48, 58-65)", "SQL commands"),
        ("Transactions [pp. 45-48]", "Transactions"),
        (
            "Read pages 4-6 and then page 7 first.",
            "Read the relevant pages and then the relevant pages first.",
        ),
        ("Study page 12", "Study the relevant pages"),
        ("Joins (see page 25 for examples) and unions", "Joins and unions"),
        ("Pages\u00a03\u20139 explain ER diagrams", "the relevant pages explain ER diagrams"),
        ("Ownership and borrowing", "Ownership and borrowing"),
        ("A pageant of pagination", "A pageant of pagination"),
        ("  extra   spaces  ", "extra spaces"),
    ],
)
def test_page_numbers_are_taken_out_of_text_and_everything_else_is_left_alone(
    text: str, expected: str
) -> None:
    assert without_page_references(text) == expected


def a_goal() -> Goal:
    return Goal.model_construct(
        title="DBMS class test",
        goal_type="exam",
        current_level="beginner",
        learning_preferences=["quizzes"],
    )


def facts(**fields: object) -> TopicFacts:
    values: dict[str, object] = {
        "item_id": uuid.uuid4(),
        "roadmap_id": uuid.uuid4(),
        "roadmap_status": "current",
        "kind": "topic",
        "title": "Normal forms (Pages 30-39)",
        "description": "Work through pages 30-39 and the examples.",
        "practice_task": "Answer 15 MCQs from pp. 30-39.",
        "estimated_minutes": 60,
        "module_title": "Design (Pages 30-44)",
        "module_summary": "Pages 30-44 cover design.",
        "objectives": ("Classify tables (Pages 33-39)",),
        "language": "en",
        "syllabus_basis": "uploaded_document",
        "earlier_titles": ("Keys (Pages 18-29)",),
        "later_titles": ("SQL (Pages 40-44)",),
    }
    values.update(fields)
    return TopicFacts(**values)  # type: ignore[arg-type]


def test_the_lesson_writer_is_given_the_topic_without_page_numbers() -> None:
    context = build_context(a_goal(), facts())

    sent = str(context.input_data())

    assert "30-39" not in sent and "Pages 30" not in sent and "pp." not in sent
    assert context.topic_title == "Normal forms"
    assert context.already_covered == ("Keys",)
    assert context.coming_next == ("SQL",)
    assert context.objectives == ("Classify tables",)


def test_the_search_for_a_topics_passages_does_not_use_page_numbers() -> None:
    query = topic_query(facts())

    assert "30" not in query and "39" not in query
    assert query.startswith("Normal forms")
