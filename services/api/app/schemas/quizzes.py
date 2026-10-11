"""Request and response contracts for quizzes, attempts, results, mastery and progress.

What a learner may see BEFORE submitting is ``QuizDetail``: prompts and options, never an answer, an
explanation or a rubric. Everything about correctness lives in ``AttemptResult``, which exists only
after a submission and is built from the learner's own answer rows. Requests reject unknown fields,
so a body that tries to name an owner, a score or a status is a validation error.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.jobs import GenerationJob
from app.schemas.lessons import ItemStudy, TopicKind

QuestionKind = Literal["multiple_choice", "true_false", "short_answer"]
Difficulty = Literal["easy", "medium", "hard"]
Purpose = Literal["check", "practice"]
AttemptStatus = Literal["grading", "graded"]
GradingMethod = Literal["deterministic", "ai_estimate", "self_review", "pending"]
Band = Literal["needs_practice", "progressing", "mastered"]
Action = Literal["take_quiz", "practice_quiz", "continue_studying", "all_done"]

MAX_ANSWER_CHARS = 2000


class QuizRequest(BaseModel):
    """Start writing a quiz for a topic."""

    model_config = ConfigDict(extra="forbid")

    purpose: Purpose = Field(
        default="check",
        description=(
            "`check` tests the topic. `practice` targets the objectives the learner scored "
            "lowest on (chosen by the server from their stored answers, never by the client)."
        ),
    )


class OptionOut(BaseModel):
    id: str
    text: str


class ObjectiveOut(BaseModel):
    id: str
    text: str


class QuestionOut(BaseModel):
    """A question as the learner sees it before answering: no key, no explanation."""

    id: UUID
    position: int
    kind: QuestionKind
    prompt: str
    # None for a short-answer question.
    options: list[OptionOut] | None
    objective_id: str
    objective_text: str | None
    difficulty: Difficulty
    max_points: int


class AttemptBrief(BaseModel):
    id: UUID
    status: AttemptStatus
    submitted_at: datetime
    # None while a short answer still waits to be marked.
    percent: float | None


class QuizSummary(BaseModel):
    id: UUID
    goal_id: UUID
    item_id: UUID
    item_title: str
    lesson_id: UUID
    purpose: Purpose
    title: str
    question_count: int
    # True when a test double, not an AI model, wrote the questions. Show it as a sample.
    is_synthetic: bool
    created_at: datetime
    status: Literal["ready", "submitted"]
    attempt: AttemptBrief | None


class QuizList(BaseModel):
    # Newest first.
    items: list[QuizSummary]


class QuizDetail(QuizSummary):
    language: str
    focus_objective_ids: list[str]
    objectives: list[ObjectiveOut]
    questions: list[QuestionOut]


class AnswerIn(BaseModel):
    """One answer: an option for a multiple-choice or true/false question, text for a short
    answer."""

    model_config = ConfigDict(extra="forbid")

    question_id: UUID
    option_id: str | None = Field(default=None, pattern=r"^[a-z0-9]{1,8}$")
    text: str | None = Field(default=None, max_length=MAX_ANSWER_CHARS)


class AttemptSubmit(BaseModel):
    """The learner's answers. A question left out counts as skipped."""

    model_config = ConfigDict(extra="forbid")

    answers: list[AnswerIn] = Field(default_factory=list[AnswerIn], max_length=12)


class RubricPointOut(BaseModel):
    id: str
    text: str
    points: int


class AnswerFeedback(BaseModel):
    """What is revealed about a question once it has been submitted."""

    explanation: str
    # Multiple choice and true/false.
    correct_option_id: str | None
    option_notes: dict[str, str]
    # Short answer.
    rubric: list[RubricPointOut] | None
    model_answer: str | None
    matched_point_ids: list[str]
    # What the marker said about a short answer (an AI estimate, unless reviewed).
    comment: str | None


class YourAnswer(BaseModel):
    option_id: str | None
    text: str | None


class AnswerResult(BaseModel):
    id: UUID
    question_id: UUID
    position: int
    kind: QuestionKind
    prompt: str
    options: list[OptionOut] | None
    objective_id: str
    objective_text: str | None
    difficulty: Difficulty
    your_answer: YourAnswer
    skipped: bool
    is_correct: bool | None
    # None while a short answer waits to be marked.
    points_awarded: float | None
    max_points: int
    # `ai_estimate` means a model's estimate against the rubric: show it as an estimate and
    # offer a review.
    grading_method: GradingMethod
    feedback: AnswerFeedback


class ObjectiveMastery(BaseModel):
    id: str
    text: str | None
    score: float
    answers: int


class TopicMasteryOut(BaseModel):
    item_id: UUID
    score: float
    band: Band
    attempts_count: int
    answers_count: int
    # Too few answers to be sure: show the score as an early estimate.
    low_confidence: bool
    objectives: list[ObjectiveMastery]
    computed_at: datetime
    algorithm_version: str
    # The configured thresholds the band was decided by, so the screen can explain it.
    needs_practice_below: float
    mastered_from: float


class RecommendationOut(BaseModel):
    action: Action
    reason: str
    item_id: UUID | None
    item_title: str | None
    # A quiz that is already written and waiting.
    quiz_id: UUID | None
    objective_ids: list[str]
    objective_texts: list[str]
    # Also go back over the lesson first (a topic that needs practice).
    review_lesson: bool


class AttemptSummary(BaseModel):
    id: UUID
    quiz_id: UUID
    goal_id: UUID
    item_id: UUID
    item_title: str
    quiz_title: str
    purpose: Purpose
    status: AttemptStatus
    submitted_at: datetime
    graded_at: datetime | None
    points_earned: float | None
    points_possible: int | None
    percent: float | None
    # Short answers still waiting for a mark.
    pending_answers: int
    # The newest marking job of this attempt (running, or failed with a reason).
    grading_job: GenerationJob | None


class AttemptResult(AttemptSummary):
    is_synthetic: bool
    answers: list[AnswerResult]
    # The topic's mastery as of now (None until a graded attempt exists).
    mastery: TopicMasteryOut | None
    recommendation: RecommendationOut | None


class ReviewRequest(BaseModel):
    """Which rubric points the learner's own answer covered. Points are computed by the server."""

    model_config = ConfigDict(extra="forbid")

    met_point_ids: list[str] = Field(
        default_factory=list[str], max_length=5, description="Ids from the answer's rubric."
    )


class TopicProgress(BaseModel):
    item_id: UUID
    title: str
    module_title: str | None
    kind: TopicKind
    study: ItemStudy
    mastery: TopicMasteryOut | None
    # A quiz that was written for the topic and not yet taken.
    pending_quiz_id: UUID | None
    last_attempt: AttemptBrief | None


AssessmentBlock = Literal[
    "lesson_required", "quiz_pending", "quiz_in_progress", "roadmap_not_current", "goal_archived"
]


class TopicAssessment(BaseModel):
    """Where a topic stands on quizzes: what is waiting, the last result, mastery, what runs."""

    item_id: UUID
    mastery: TopicMasteryOut | None
    # A quiz that was written for the topic and not yet taken.
    pending_quiz_id: UUID | None
    last_attempt: AttemptBrief | None
    # The newest quiz job of the topic (writing now, or the last failure).
    job: GenerationJob | None
    # Whether a quiz can be started now, and if not, why.
    can_start: bool
    blocked_by: AssessmentBlock | None
    recommendation: RecommendationOut | None


class ProgressCounts(BaseModel):
    total: int
    mastered: int
    progressing: int
    needs_practice: int
    not_assessed: int


class GoalProgress(BaseModel):
    goal_id: UUID
    roadmap_id: UUID | None
    topics: list[TopicProgress]
    counts: ProgressCounts
    recommendation: RecommendationOut | None
