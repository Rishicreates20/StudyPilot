"""What the lesson writer is asked to produce, and the typed document that is stored and rendered.

Two shapes, on purpose:

* ``DraftLesson`` is what the MODEL fills in. It is flat (a block is one object with a ``type`` and
  the fields that type uses, unused ones left empty) because that is the part of JSON Schema that
  every provider accepts reliably: no ``oneOf``, no nulls. The field descriptions double as
  instructions to the model. Limits here only reject shapes that make no sense; the real rules are
  in ``validation.py``.
* ``Lesson`` is the strict document that is stored and sent to the browser. Its blocks are a
  discriminated union, so a code block always has code and a list always has items, and section ids
  are assigned by code. ``build_lesson`` turns the first into the second or reports what is wrong.

Lesson content is therefore never "a string the model wrote": it is a typed, bounded structure that
is validated when it is made, again when it is stored, and again whenever it is read back.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

# Bump when the stored document's shape changes; old lessons are read by their own version.
# (``grounding`` was added with default "none", so lessons stored before it still read as v1.)
CONTENT_VERSION = 1

MIN_SECTIONS = 2
MAX_SECTIONS = 8
MAX_BLOCKS_PER_SECTION = 12
MAX_PARAGRAPH_CHARS = 4000
MAX_CODE_CHARS = 4000

BlockType = Literal["paragraph", "list", "code", "callout"]
CalloutKind = Literal["tip", "note", "warning"]
# Whether a lesson rests on the learner's own uploaded material. Set by CODE, never by the model:
# "none" = the goal has no ready documents (or the lesson predates documents); "sources" = it cites
# passages that were really retrieved; "no_match" = the learner has documents but nothing in them
# matched this topic (or the lesson cited none), so it relies on general knowledge and says so.
Grounding = Literal["none", "sources", "no_match"]
# How a regeneration is asked to differ from the version it starts from.
Adjust = Literal["simpler", "more_examples", "deeper"]

ShortText = Annotated[str, Field(min_length=1, max_length=400)]
StepText = Annotated[str, Field(min_length=1, max_length=500)]


# --- What the model fills in --------------------------------------------------------------------

# The draft is deliberately looser than the stored document. A model that writes a 110-character
# title (the stored limit is 100) should not cost a whole second call: purely cosmetic fields are
# trimmed to size when the document is built, and content fields that are still too long are
# reported by the stored model's own limits (see ``build_lesson``), so ONE repair can ask for
# them to be shortened. The limits below only stop absurd answers; the limits the model is TOLD are
# in the field descriptions (the provider schema drops length keywords).
_LOOSE = 3


class _Draft(BaseModel):
    # A field the model adds that we never asked for is harmless: nothing it adds is stored.
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


class DraftBlock(_Draft):
    type: BlockType = Field(
        description=(
            '"paragraph" (uses text), "list" (uses items and ordered), "code" (uses language and '
            'code, optionally caption) or "callout" (uses callout_kind, text, optionally title). '
            "Leave the fields a type does not use empty."
        )
    )
    text: str = Field(
        default="",
        max_length=MAX_PARAGRAPH_CHARS * _LOOSE,
        description=(
            f"Paragraph text, or the body of a callout. Plain text, at most {MAX_PARAGRAPH_CHARS} "
            "characters."
        ),
    )
    items: list[Annotated[str, Field(max_length=500 * _LOOSE)]] = Field(
        default_factory=list[str],
        max_length=40,
        description="The entries of a list: at most 20, each at most 500 characters.",
    )
    ordered: bool = Field(default=False, description="true for a numbered list, false for bullets.")
    language: str = Field(
        default="",
        description='Lowercase language of a code block, such as "python". Use "text" for output.',
    )
    code: str = Field(
        default="",
        max_length=MAX_CODE_CHARS * _LOOSE,
        description=f"The code itself, at most {MAX_CODE_CHARS} characters.",
    )
    caption: str = Field(default="", description="Optional line under a code block.")
    callout_kind: CalloutKind = Field(
        default="note", description='"tip", "note" or "warning" (a common mistake or a risk).'
    )
    title: str = Field(
        default="", description="Optional short title of a callout, at most 100 characters."
    )


class DraftSection(_Draft):
    heading: str = Field(
        min_length=3,
        max_length=120 * _LOOSE,
        description="A short, plain heading of at most 120 characters.",
    )
    blocks: list[DraftBlock] = Field(
        min_length=1,
        max_length=MAX_BLOCKS_PER_SECTION * _LOOSE,
        description=(
            f"The section's content in reading order, at most {MAX_BLOCKS_PER_SECTION} blocks."
        ),
    )


class DraftDefinition(_Draft):
    term: str = Field(min_length=1, max_length=80 * _LOOSE, description="At most 80 characters.")
    meaning: str = Field(
        min_length=5,
        max_length=400 * _LOOSE,
        description="A plain-language definition of at most 400 characters.",
    )


class DraftExample(_Draft):
    title: str = Field(min_length=3, max_length=120 * _LOOSE, description="At most 120 characters.")
    problem: str = Field(
        min_length=10,
        max_length=800 * _LOOSE,
        description="The situation or question, at most 800 characters.",
    )
    steps: list[Annotated[str, Field(min_length=1, max_length=500 * _LOOSE)]] = Field(
        min_length=1,
        max_length=10 * _LOOSE,
        description="The reasoning, one step per entry: at most 10 steps of 500 characters.",
    )
    answer: str = Field(
        min_length=3,
        max_length=600 * _LOOSE,
        description="The result, and why it matters, at most 600 characters.",
    )


class DraftMisconception(_Draft):
    misconception: str = Field(
        min_length=5,
        max_length=300 * _LOOSE,
        description="What learners often wrongly believe, at most 300 characters.",
    )
    correction: str = Field(
        min_length=5,
        max_length=500 * _LOOSE,
        description="What is actually true, at most 500 characters.",
    )


class DraftSimpleExplanation(_Draft):
    paragraphs: list[Annotated[str, Field(min_length=5, max_length=700 * _LOOSE)]] = Field(
        min_length=1,
        max_length=5 * _LOOSE,
        description=(
            "The same topic in everyday words for someone with no background: short sentences, "
            "every unfamiliar word explained, no new facts. At most 5 paragraphs of 700 characters."
        ),
    )
    analogy: str = Field(
        default="",
        description="One familiar comparison, at most 500 characters. Empty if none fits.",
    )


class DraftReference(_Draft):
    source_id: str = Field(min_length=1, max_length=64)
    chunk_id: str = Field(min_length=1, max_length=64)
    note: str = Field(default="", description="What this source supports, briefly.")


class DraftLesson(_Draft):
    language: str = Field(
        min_length=2, max_length=3, description="ISO code of the language the lesson is written in."
    )
    title: str = Field(min_length=3, max_length=200 * _LOOSE, description="At most 200 characters.")
    learning_objectives: list[Annotated[str, Field(min_length=5, max_length=300 * _LOOSE)]] = Field(
        min_length=2,
        max_length=6,
        description=(
            "What the learner will be able to do after this lesson, starting with a verb: 2 to 6 "
            "entries of at most 300 characters."
        ),
    )
    sections: list[DraftSection] = Field(
        min_length=MIN_SECTIONS,
        max_length=MAX_SECTIONS,
        description="The lesson body, from intuition to detail. 3 to 6 sections is typical.",
    )
    definitions: list[DraftDefinition] = Field(
        default_factory=list[DraftDefinition],
        max_length=12 * _LOOSE,
        description="The key terms of this topic, each defined once: at most 12.",
    )
    worked_examples: list[DraftExample] = Field(
        min_length=1,
        max_length=4 * _LOOSE,
        description="Complete examples worked through step by step: 1 to 4.",
    )
    common_misconceptions: list[DraftMisconception] = Field(
        default_factory=list[DraftMisconception],
        max_length=5 * _LOOSE,
        description="At most 5.",
    )
    summary: list[Annotated[str, Field(min_length=1, max_length=400 * _LOOSE)]] = Field(
        min_length=2,
        max_length=8 * _LOOSE,
        description="The key takeaways, one per entry: 2 to 8 entries of at most 400 characters.",
    )
    simple_explanation: DraftSimpleExplanation
    source_references: list[DraftReference] = Field(
        default_factory=list[DraftReference],
        max_length=20,
        description=(
            "Only sources that were supplied in the input and that the lesson really uses. "
            "Leave empty when no source material was supplied."
        ),
    )


# --- What is stored and shown -------------------------------------------------------------------


class _Stored(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ParagraphBlock(_Stored):
    type: Literal["paragraph"] = "paragraph"
    text: str = Field(min_length=1, max_length=MAX_PARAGRAPH_CHARS)


class ListBlock(_Stored):
    type: Literal["list"] = "list"
    ordered: bool
    items: list[Annotated[str, Field(min_length=1, max_length=500)]] = Field(
        min_length=1, max_length=20
    )


class CodeBlock(_Stored):
    type: Literal["code"] = "code"
    language: str = Field(min_length=1, max_length=30, pattern=r"^[a-z0-9+#._-]+$")
    code: str = Field(min_length=1, max_length=MAX_CODE_CHARS)
    caption: str | None = Field(default=None, max_length=200)


class CalloutBlock(_Stored):
    type: Literal["callout"] = "callout"
    kind: CalloutKind
    title: str | None = Field(default=None, max_length=100)
    text: str = Field(min_length=1, max_length=MAX_PARAGRAPH_CHARS)


Block = Annotated[
    ParagraphBlock | ListBlock | CodeBlock | CalloutBlock, Field(discriminator="type")
]


class LessonSection(_Stored):
    # Assigned by code ("s1", "s2" ...) and unique within a lesson; progress is recorded against it.
    id: str = Field(pattern=r"^s[0-9]{1,2}$")
    heading: str = Field(min_length=3, max_length=120)
    blocks: list[Block] = Field(min_length=1, max_length=MAX_BLOCKS_PER_SECTION)


class Definition(_Stored):
    term: str = Field(min_length=1, max_length=80)
    meaning: str = Field(min_length=5, max_length=400)


class WorkedExample(_Stored):
    title: str = Field(min_length=3, max_length=120)
    problem: str = Field(min_length=10, max_length=800)
    steps: list[StepText] = Field(min_length=1, max_length=10)
    answer: str = Field(min_length=3, max_length=600)


class Misconception(_Stored):
    misconception: str = Field(min_length=5, max_length=300)
    correction: str = Field(min_length=5, max_length=500)


class SimpleExplanation(_Stored):
    paragraphs: list[Annotated[str, Field(min_length=5, max_length=700)]] = Field(
        min_length=1, max_length=5
    )
    analogy: str | None = Field(default=None, max_length=500)


class SourceReference(_Stored):
    """A pointer to a passage of the learner's own uploaded material that supports the lesson.

    In what the model writes these are short labels from the prompt ("S1" / "P2"); before a lesson
    is stored, code replaces them with the real document and passage ids.
    """

    source_id: str = Field(min_length=1, max_length=64)
    chunk_id: str = Field(min_length=1, max_length=64)
    note: str | None = Field(default=None, max_length=200)


class Lesson(_Stored):
    """The stored lesson document (content version ``CONTENT_VERSION``)."""

    language: str = Field(pattern=r"^[a-z]{2,3}$")
    title: str = Field(min_length=3, max_length=200)
    learning_objectives: list[Annotated[str, Field(min_length=5, max_length=300)]] = Field(
        min_length=2, max_length=6
    )
    sections: list[LessonSection] = Field(min_length=MIN_SECTIONS, max_length=MAX_SECTIONS)
    definitions: list[Definition] = Field(max_length=12)
    worked_examples: list[WorkedExample] = Field(min_length=1, max_length=4)
    common_misconceptions: list[Misconception] = Field(max_length=5)
    summary: list[ShortText] = Field(min_length=2, max_length=8)
    simple_explanation: SimpleExplanation
    source_references: list[SourceReference] = Field(max_length=20)
    grounding: Grounding = "none"

    def section_ids(self) -> list[str]:
        return [section.id for section in self.sections]
