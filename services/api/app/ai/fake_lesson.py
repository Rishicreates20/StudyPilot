"""The built-in answer of ``FakeProvider`` to a lesson request.

It builds a small, always-valid lesson from the same facts the real prompt is rendered from, and it
says so in the lesson itself: the title, the first callout and the stored ``is_synthetic`` flag all
state that this is a sample from the test provider and not AI-generated content. It exists so the
whole pipeline (queue, worker, validation, storage, study UI) can be exercised without a model.
"""

from collections.abc import Mapping
from typing import Any

from app.ai.fake import Reply
from app.ai.lesson.schema import (
    DraftBlock,
    DraftDefinition,
    DraftExample,
    DraftLesson,
    DraftMisconception,
    DraftReference,
    DraftSection,
    DraftSimpleExplanation,
)
from app.ai.provider import StructuredRequest

_SAMPLE_NOTE = "This is a sample lesson from the built-in test provider, not an AI-generated one."
_ADJUSTMENTS = {
    "simpler": "This version was asked to use simpler words.",
    "more_examples": "This version was asked to include more worked examples.",
    "deeper": "This version was asked to go into more depth.",
}


def _paragraph(text: str) -> DraftBlock:
    return DraftBlock(type="paragraph", text=text)


def sample_lesson(input_data: Mapping[str, Any]) -> DraftLesson:
    topic: Mapping[str, Any] = input_data["topic"]
    title = str(topic["title"]).strip()
    description = str(topic["description"]).strip()
    practice = topic.get("practice_task")
    change: Mapping[str, Any] | None = input_data.get("change_request")
    adjust = change.get("adjust") if change else None
    feedback = change.get("feedback") if change else None
    sources: list[Mapping[str, Any]] = list(input_data.get("source_material") or [])

    intro = f"This sample lesson stands in for a real lesson about {title}. {description}"
    if adjust in _ADJUSTMENTS:
        intro += f" {_ADJUSTMENTS[adjust]}"
    if feedback:
        intro += f" The learner also wrote: {str(feedback)[:120]}"

    sections = [
        DraftSection(
            heading="What this topic is about",
            blocks=[
                _paragraph(intro),
                DraftBlock(
                    type="callout", callout_kind="warning", title="Sample", text=_SAMPLE_NOTE
                ),
            ],
        ),
        DraftSection(
            heading="The main idea",
            blocks=[
                _paragraph(
                    "A real lesson would explain the central idea in plain words, starting from "
                    "what you already know and building up one step at a time."
                ),
                DraftBlock(
                    type="list",
                    ordered=True,
                    items=[
                        "Start with a simple picture of the idea.",
                        "Add the rules that make it precise.",
                        "Check your understanding on a small case.",
                    ],
                ),
            ],
        ),
        DraftSection(
            heading="A small example",
            blocks=[
                _paragraph(
                    "Examples turn an idea into something you can check. A real lesson would "
                    "show one that fits your goal and walk through it."
                ),
                DraftBlock(
                    type="code",
                    language="text",
                    code="input -> steps -> result",
                    caption="Placeholder for a real code example",
                ),
            ],
        ),
        DraftSection(
            heading="Try it yourself",
            blocks=[
                _paragraph(
                    f"Practice makes it stick. {practice}"
                    if practice
                    else "Practice makes it stick: explain the idea aloud in your own words."
                ),
                DraftBlock(
                    type="callout",
                    callout_kind="tip",
                    text="If you get stuck, go back to the main idea and try a smaller case.",
                ),
            ],
        ),
    ]
    if adjust == "deeper":
        sections.insert(
            3,
            DraftSection(
                heading="Edge cases and why the rules hold",
                blocks=[
                    _paragraph(
                        "A deeper version looks at the unusual cases and explains why the rules "
                        "are the way they are, so you can reason about situations the lesson "
                        "never listed."
                    )
                ],
            ),
        )

    examples = [
        DraftExample(
            title="A sample worked example",
            problem="A real lesson would pose a small problem about this topic here.",
            steps=["State what is known.", "Apply the main idea.", "Check the result."],
            answer="The result would be stated here, with why it matters.",
        )
    ]
    if adjust == "more_examples":
        examples.append(
            DraftExample(
                title="A second sample example",
                problem="A second example would show the idea in a slightly different setting.",
                steps=["Compare with the first example.", "Spot what changed.", "Apply the idea."],
                answer="Seeing the idea twice makes the pattern clear.",
            )
        )

    return DraftLesson(
        language=str(input_data["language"]),
        title=f"Sample lesson: {title}"[:200],
        learning_objectives=[
            f"Explain the main idea of {title[:100]} in your own words",
            "Work through a small example step by step",
        ],
        sections=sections,
        definitions=[
            DraftDefinition(
                term=title[:60],
                meaning="The topic of this lesson, described here only as a placeholder.",
            )
        ],
        worked_examples=examples,
        common_misconceptions=[
            DraftMisconception(
                misconception="A sample lesson contains everything you need to learn the topic.",
                correction=(
                    "It only shows how a lesson looks. Generate a real one with an AI model."
                ),
            )
        ],
        summary=[
            "This was a sample lesson that shows the layout of a real one.",
            "A real lesson explains, shows an example and lets you practise.",
        ],
        simple_explanation=DraftSimpleExplanation(
            paragraphs=[
                f"Think of this lesson as a picture frame with nothing in it yet. It shows where "
                f"the explanation of {title[:80]} would go, in short and simple sentences.",
                "When a real model writes the lesson, the same spot holds a plain, friendly "
                "explanation of the topic.",
            ],
            analogy="Like a recipe card before anyone has written the recipe on it.",
        ),
        source_references=[
            DraftReference(
                source_id=str(sources[0]["source_id"]),
                chunk_id=str(sources[0]["chunk_id"]),
                note="Used for the sample explanation",
            )
        ]
        if sources
        else [],
    )


def lesson_responder(request: StructuredRequest) -> Reply:
    return sample_lesson(request.input_data)
