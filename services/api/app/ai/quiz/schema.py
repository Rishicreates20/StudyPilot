"""What the quiz writer is asked to produce, and the typed questions that are stored.

Two shapes, as for lessons (ADR-032):

* ``DraftQuiz`` is what the MODEL fills in: flat, no ``oneOf``, no nulls, and deliberately looser
  than the stored shape (a limit the model overshoots by a few characters should not cost a second
  call). The right answer is given as the *text* of the correct option, not an index, so a mix-up
  between the two is something code can see.
* ``BuiltQuiz`` is what code makes of it: questions are a discriminated union (multiple choice, true
  or false, short answer), option ids are assigned by code AFTER the options are shuffled (so the
  right answer is not always first), and rubric points get ids. The learner-visible part (prompt,
  options) and the secret part (the correct option, the rubric, the explanation) are split by the
  store: the secret part goes to ``question_answer_keys``, which no browser-facing role can read.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

MAX_QUESTIONS = 12

QuestionKind = Literal["multiple_choice", "true_false", "short_answer"]
Difficulty = Literal["easy", "medium", "hard"]

# What a question is worth, and how much it weighs in mastery.
DIFFICULTY_POINTS: dict[str, int] = {"easy": 1, "medium": 2, "hard": 3}

_LOOSE = 3


# --- What the model fills in --------------------------------------------------------------------


class _Draft(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


class DraftRubricPoint(_Draft):
    text: str = Field(
        min_length=5,
        max_length=300 * _LOOSE,
        description="One thing a good answer says, checkable as present or absent. "
        "At most 300 characters.",
    )
    points: int = Field(default=1, ge=1, le=3, description="1 to 3: how much this point matters.")


class DraftQuestion(_Draft):
    kind: QuestionKind = Field(
        description=(
            '"multiple_choice" (4 options, one correct), "true_false" (a statement) or '
            '"short_answer" (a few sentences, graded against a rubric).'
        )
    )
    prompt: str = Field(
        min_length=10,
        max_length=1500 * _LOOSE,
        description="The question or statement, at most 1500 characters. Plain text.",
    )
    objective_id: str = Field(
        min_length=1,
        max_length=60,
        description="The id of the objective this question tests, exactly as given in the input.",
    )
    difficulty: Difficulty
    options: list[Annotated[str, Field(max_length=300 * _LOOSE)]] = Field(
        default_factory=list[str],
        max_length=12,
        description=(
            "multiple_choice only: exactly 4 answer options of at most 300 characters. "
            "Leave empty for the other kinds."
        ),
    )
    correct_option: str = Field(
        default="",
        max_length=300 * _LOOSE,
        description=(
            'multiple_choice: the EXACT text of the one correct option, copied from "options". '
            'true_false: "true" or "false". Leave empty for short_answer.'
        ),
    )
    option_notes: list[Annotated[str, Field(max_length=400 * _LOOSE)]] = Field(
        default_factory=list[str],
        max_length=12,
        description=(
            "multiple_choice only, optional: one short sentence per option, in the same order as "
            '"options", saying why it is right or wrong.'
        ),
    )
    explanation: str = Field(
        min_length=10,
        max_length=2000 * _LOOSE,
        description=(
            "Why the correct answer is correct and what mistake the wrong ones come from, at most "
            "2000 characters. For short_answer, what a complete answer covers."
        ),
    )
    rubric: list[DraftRubricPoint] = Field(
        default_factory=list[DraftRubricPoint],
        max_length=10,
        description="short_answer only: 2 to 5 points a complete answer must cover.",
    )
    model_answer: str = Field(
        default="",
        max_length=1500 * _LOOSE,
        description="short_answer only: an example of a complete answer, at most 1500 characters.",
    )


class DraftQuiz(_Draft):
    language: str = Field(
        min_length=2, max_length=3, description="ISO code of the language the quiz is written in."
    )
    title: str = Field(min_length=3, max_length=200 * _LOOSE, description="At most 200 characters.")
    questions: list[DraftQuestion] = Field(
        min_length=1,
        max_length=MAX_QUESTIONS * 2,
        description="The questions, in the order they are asked.",
    )


# --- What is stored -----------------------------------------------------------------------------


class _Built(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BuiltOption(_Built):
    id: str = Field(pattern=r"^(?:[a-f]|true|false)$")
    text: str = Field(min_length=1, max_length=300)


class BuiltRubricPoint(_Built):
    id: str = Field(pattern=r"^p[1-9]$")
    text: str = Field(min_length=5, max_length=300)
    points: int = Field(ge=1, le=3)


class _BuiltQuestion(_Built):
    prompt: str = Field(min_length=10, max_length=1500)
    objective_id: str = Field(min_length=1, max_length=20)
    difficulty: Difficulty
    explanation: str = Field(min_length=10, max_length=2000)

    @property
    def max_points(self) -> int:
        return DIFFICULTY_POINTS[self.difficulty]


class BuiltMultipleChoice(_BuiltQuestion):
    kind: Literal["multiple_choice"] = "multiple_choice"
    options: list[BuiltOption] = Field(min_length=4, max_length=4)
    correct_option_id: str = Field(pattern=r"^[a-f]$")
    # option id -> why it is right or wrong
    option_notes: dict[str, str] = Field(default_factory=dict[str, str])


class BuiltTrueFalse(_BuiltQuestion):
    kind: Literal["true_false"] = "true_false"
    options: list[BuiltOption] = Field(min_length=2, max_length=2)
    correct_option_id: Literal["true", "false"]


class BuiltShortAnswer(_BuiltQuestion):
    kind: Literal["short_answer"] = "short_answer"
    rubric: list[BuiltRubricPoint] = Field(min_length=2, max_length=5)
    model_answer: str = Field(min_length=10, max_length=1500)


BuiltQuestion = Annotated[
    BuiltMultipleChoice | BuiltTrueFalse | BuiltShortAnswer, Field(discriminator="kind")
]


class BuiltQuiz(_Built):
    language: str = Field(pattern=r"^[a-z]{2,3}$")
    title: str = Field(min_length=3, max_length=200)
    questions: list[BuiltQuestion] = Field(min_length=1, max_length=MAX_QUESTIONS)
