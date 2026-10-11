import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const nav = vi.hoisted(() => ({ refresh: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: nav.refresh }) }));

const actions = vi.hoisted(() => ({
  startQuizAction: vi.fn(),
  cancelQuizAction: vi.fn(),
  cancelMarkingAction: vi.fn(),
  retryQuizAction: vi.fn(),
  submitQuizAction: vi.fn(),
  reviewAnswerAction: vi.fn(),
  regradeAction: vi.fn(),
}));
vi.mock("@/lib/quizzes/actions", () => actions);

import { QuizForm } from "@/components/quiz/quiz-form";
import { RecommendationCard } from "@/components/quiz/recommendation-card";
import { ResultsView } from "@/components/quiz/results-view";
import { TopicAssessment } from "@/components/quiz/topic-assessment";
import { TopicProgressList } from "@/components/quiz/topic-progress-list";
import { ESTIMATE_NOTE } from "@/lib/quizzes/labels";
import { GOAL, ITEM, study } from "@/test-support/lessons";
import {
  answer,
  assessment,
  ATTEMPT,
  goalProgress,
  mastery,
  QUIZ,
  quiz,
  quizJob,
  recommendation,
  result,
  shortAnswer,
  topicProgress,
} from "@/test-support/quizzes";

beforeEach(() => {
  vi.clearAllMocks();
});

describe("QuizForm", () => {
  function renderForm(overrides = {}) {
    return render(<QuizForm goalId={GOAL} itemId={ITEM} quiz={quiz(overrides)} />);
  }

  it("shows every question with a way to answer it that fits its kind", () => {
    renderForm();

    const questions = screen.getAllByRole("group");
    expect(questions).toHaveLength(3);
    // multiple choice: four radio options; true/false: two; short answer: a text box
    expect(within(questions[0]!).getAllByRole("radio")).toHaveLength(4);
    expect(within(questions[1]!).getAllByRole("radio")).toHaveLength(2);
    expect(within(questions[2]!).getByRole("textbox")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "It is dropped" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /submit answers/i })).toBeInTheDocument();
  });

  it("names each question group by its prompt", () => {
    renderForm();

    expect(
      screen.getByRole("group", { name: /what happens to a value when its owner goes out/i }),
    ).toBeInTheDocument();
  });

  it("shows no verdict before submitting: nothing is pre-selected and no answer is revealed", () => {
    const { container } = renderForm();

    expect(container.querySelectorAll("input:checked")).toHaveLength(0);
    expect(screen.queryByText(/correct answer/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/^why$/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/model answer/i)).not.toBeInTheDocument();
  });

  it("counts the answered questions as they are answered, and says blanks score zero", async () => {
    const user = userEvent.setup();
    renderForm();
    const status = screen.getByRole("status");
    expect(status).toHaveTextContent("0 of 3 answered");
    expect(status).toHaveTextContent(/blank scores zero/i);

    await user.click(screen.getByRole("radio", { name: "It is dropped" }));
    expect(status).toHaveTextContent("1 of 3 answered");

    await user.click(screen.getByRole("radio", { name: "True" }));
    await user.type(screen.getByRole("textbox"), "Safety");
    expect(status).toHaveTextContent("3 of 3 answered");
    expect(status).toHaveTextContent(/submitted once/i);
  });

  it("sends each answer under a field named for its question", () => {
    const { container } = renderForm();

    const names = [...container.querySelectorAll<HTMLInputElement>("input[type=radio]")].map(
      (input) => input.name,
    );
    expect(new Set(names)).toEqual(
      new Set(["q_aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1", "q_aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa2"]),
    );
    expect(container.querySelector("textarea")?.name).toBe(
      "q_aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa3",
    );
    expect(container.querySelector("textarea")?.maxLength).toBe(2000);
  });

  it("labels each question with its kind, difficulty and worth", () => {
    renderForm();

    expect(screen.getByText("Multiple choice")).toBeInTheDocument();
    expect(screen.getByText("True or false")).toBeInTheDocument();
    expect(screen.getByText("Short answer")).toBeInTheDocument();
    expect(screen.getByText("Hard")).toBeInTheDocument();
    expect(screen.getByText("3 points")).toBeInTheDocument();
  });
});

describe("ResultsView", () => {
  function renderResults(overrides = {}, props: { readOnly?: boolean } = {}) {
    return render(
      <ResultsView
        goalId={GOAL}
        itemId={ITEM}
        result={result(overrides)}
        timeZone="UTC"
        readOnly={props.readOnly ?? false}
      />,
    );
  }

  it("shows the score and points", () => {
    renderResults();

    expect(screen.getAllByText("25%").length).toBeGreaterThan(0);
    expect(screen.getByText(/1\.5 of 6 points/)).toBeInTheDocument();
  });

  it("shows the right answer, the learner's choice and the explanation after submission", () => {
    renderResults();

    const wrong = screen.getAllByRole("article")[0]!;
    expect(within(wrong).getByText("Not quite")).toBeInTheDocument();
    expect(within(wrong).getByText("Correct answer")).toBeInTheDocument();
    expect(within(wrong).getByText("Your answer")).toBeInTheDocument();
    expect(
      within(wrong).getByText("The owner's scope ends, so Rust drops the value."),
    ).toBeInTheDocument();
    expect(within(wrong).getByText("Right: drop runs at the end of scope.")).toBeInTheDocument();
  });

  it("marks a right answer, and an unanswered question, in words", () => {
    renderResults({
      answers: [
        answer({
          is_correct: true,
          points_awarded: 1,
          your_answer: { option_id: "a", text: null },
        }),
        answer({
          id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb9",
          skipped: true,
          is_correct: false,
          your_answer: { option_id: null, text: null },
        }),
      ],
    });

    expect(screen.getByText("Correct")).toBeInTheDocument();
    expect(screen.getByText("Not answered")).toBeInTheDocument();
  });

  it("says a short answer left blank was not answered, and that it scored nothing", () => {
    renderResults({
      answers: [
        shortAnswer({
          skipped: true,
          your_answer: { option_id: null, text: null },
          points_awarded: 0,
          grading_method: "deterministic",
          is_correct: null,
          feedback: { ...shortAnswer().feedback, matched_point_ids: [], comment: null },
        }),
      ],
    });

    const article = screen.getByRole("article");
    expect(within(article).getByText("Not answered")).toBeInTheDocument();
    expect(within(article).getByText("0 of 3 points")).toBeInTheDocument();
    expect(within(article).getByText("You left this blank.")).toBeInTheDocument();
    expect(within(article).queryByText("Marked automatically")).not.toBeInTheDocument();
    expect(screen.queryByText("Disagree? Mark it yourself")).not.toBeInTheDocument();
  });

  it("labels a model's marking of a short answer as an estimate, with the rubric and model answer", () => {
    renderResults();

    const article = screen.getAllByRole("article")[1]!;
    expect(within(article).getByText("AI estimate")).toBeInTheDocument();
    expect(within(article).getByText(ESTIMATE_NOTE)).toBeInTheDocument();
    expect(within(article).getAllByText(/Says it manages memory/)[0]).toBeInTheDocument();
    expect(within(article).getByText(/\(covered\)/)).toBeInTheDocument();
    expect(within(article).getByText(/\(not covered\)/)).toBeInTheDocument();
    expect(within(article).getByText(/with no garbage collector/)).toBeInTheDocument();
    expect(within(article).getByText(/mention the missing collector/)).toBeInTheDocument();
    expect(within(article).getByText("1.5 of 3 points")).toBeInTheDocument();
    expect(screen.getByText("Includes an AI estimate")).toBeInTheDocument();
  });

  it("lets the learner review the estimate by ticking the rubric points they covered", async () => {
    const user = userEvent.setup();
    renderResults();

    const article = screen.getAllByRole("article")[1]!;
    await user.click(within(article).getByText("Disagree? Mark it yourself"));

    const boxes = within(article).getAllByRole("checkbox");
    expect(boxes).toHaveLength(2);
    expect(boxes[0]).toBeChecked();
    expect(boxes[1]).not.toBeChecked();
    expect(boxes[0]).toHaveAttribute("name", "met");
    expect(within(article).getByRole("button", { name: "Save my marking" })).toBeInTheDocument();
  });

  it("calls the learner's own marking theirs, not an estimate", () => {
    renderResults({
      answers: [
        shortAnswer({
          grading_method: "self_review",
          feedback: { ...shortAnswer().feedback, comment: null },
        }),
      ],
    });

    const article = screen.getByRole("article");
    expect(within(article).getByText("Marked by you")).toBeInTheDocument();
    expect(within(article).queryByText(ESTIMATE_NOTE)).not.toBeInTheDocument();
    expect(screen.getByText("Includes your own marking")).toBeInTheDocument();
  });

  it("keeps results read-only for an archived goal", () => {
    renderResults({}, { readOnly: true });

    expect(screen.queryByText("Disagree? Mark it yourself")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /practise these parts/i })).not.toBeInTheDocument();
  });

  it("shows how well the topic is known and which objectives are weak", () => {
    renderResults();

    expect(screen.getByText(/How well you know “Ownership”/)).toBeInTheDocument();
    expect(screen.getAllByText("Needs practice").length).toBeGreaterThan(0);
    expect(screen.getByText(/20% · weak/)).toBeInTheDocument();
    expect(screen.getByText(/80%/)).toBeInTheDocument();
    expect(screen.getByText(/Based on 1 quiz and 5 answers/)).toBeInTheDocument();
  });

  it("recommends a small remedy for a weak topic rather than starting over", () => {
    renderResults();

    expect(screen.getByText("Your next step")).toBeInTheDocument();
    expect(screen.getByText(/You scored 52% on/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /practise these parts/i })).toBeInTheDocument();
    expect(screen.getByText(/You don’t need to repeat the rest of the course/)).toBeInTheDocument();
    expect(
      screen.getByText("Use references to borrow a value", { selector: "li" }),
    ).toBeInTheDocument();
  });

  it("waits for the short answers: no score yet, and the marking's progress is shown", () => {
    renderResults({
      status: "grading",
      percent: null,
      points_earned: null,
      points_possible: null,
      graded_at: null,
      pending_answers: 1,
      mastery: null,
      recommendation: null,
      grading_job: quizJob({ id: "g1", job_type: "grade", stage: "grading", status: "running" }),
      answers: [answer(), shortAnswer({ grading_method: "pending", points_awarded: null })],
    });

    expect(
      screen.getByText(/Your score appears once your short answer is marked/),
    ).toBeInTheDocument();
    expect(screen.getByText("Marking your short answers")).toBeInTheDocument();
    expect(screen.getByText("Waiting to be marked")).toBeInTheDocument();
    expect(screen.queryByText(/How well you know/)).not.toBeInTheDocument();
  });

  it("offers to mark again when marking failed, and says the answers are safe", () => {
    renderResults({
      status: "grading",
      percent: null,
      pending_answers: 1,
      mastery: null,
      recommendation: null,
      grading_job: quizJob({
        job_type: "grade",
        status: "failed",
        error_message: "The AI couldn't estimate a score for your short answer this time.",
      }),
      answers: [answer(), shortAnswer({ grading_method: "pending", points_awarded: null })],
    });

    expect(screen.getByText("Your short answers haven’t been marked")).toBeInTheDocument();
    expect(screen.getByText(/couldn't estimate a score/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /mark them again/i })).toBeInTheDocument();
  });

  it("calls a built-in test quiz a sample", () => {
    renderResults({ is_synthetic: true });

    expect(screen.getByText("Sample quiz (not written by an AI)")).toBeInTheDocument();
  });
});

describe("TopicAssessment", () => {
  function renderCard(data = assessment()) {
    return render(<TopicAssessment goalId={GOAL} itemId={ITEM} assessment={data} timeZone="UTC" />);
  }

  it("invites a first quiz when a lesson exists and nothing is waiting", () => {
    renderCard();

    expect(screen.getByRole("heading", { name: /check what you’ve learned/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Take a quiz" })).toBeInTheDocument();
    expect(screen.queryByText("How well you know this topic")).not.toBeInTheDocument();
  });

  it("links to a quiz that is waiting", () => {
    renderCard(assessment({ pending_quiz_id: QUIZ, can_start: false, blocked_by: "quiz_pending" }));

    expect(screen.getByText("Your quiz is ready")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /take the quiz/i })).toHaveAttribute(
      "href",
      `/goals/${GOAL}/learn/${ITEM}/quiz/${QUIZ}`,
    );
    expect(screen.queryByRole("button", { name: "Take a quiz" })).not.toBeInTheDocument();
  });

  it("shows a quiz being written, with its progress", () => {
    renderCard(
      assessment({
        job: quizJob({ status: "running", stage: "writing" }),
        can_start: false,
        blocked_by: "quiz_in_progress",
      }),
    );

    expect(screen.getByText("Writing your quiz")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
  });

  it("shows why the last attempt failed and offers to try again", () => {
    renderCard(
      assessment({
        job: quizJob({ status: "failed", error_message: "It didn't pass our checks." }),
      }),
    );

    expect(screen.getByText("We couldn’t write the quiz")).toBeInTheDocument();
    expect(screen.getByText("It didn't pass our checks.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /try again/i })).toBeInTheDocument();
  });

  it("says a lesson is needed first", () => {
    renderCard(assessment({ can_start: false, blocked_by: "lesson_required" }));

    expect(screen.getByText(/Study this topic.s lesson first/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Take a quiz" })).not.toBeInTheDocument();
  });

  it("shows mastery, the last result and the recommended practice for a weak topic", () => {
    renderCard(
      assessment({
        mastery: mastery(),
        last_attempt: {
          id: ATTEMPT,
          status: "graded",
          submitted_at: "2026-10-11T10:05:00Z",
          percent: 52,
        },
        recommendation: recommendation(),
      }),
    );

    expect(screen.getByText("How well you know this topic")).toBeInTheDocument();
    expect(screen.getByText("Needs practice")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /see your last results/i })).toHaveAttribute(
      "href",
      `/goals/${GOAL}/learn/${ITEM}/results/${ATTEMPT}`,
    );
    expect(screen.getByRole("button", { name: /practise these parts/i })).toBeInTheDocument();
    // the plain "take another quiz" card steps aside for the recommendation
    expect(screen.queryByRole("button", { name: "Take another quiz" })).not.toBeInTheDocument();
  });

  it("offers a waiting practice quiz once, through the recommendation, for a weak topic", () => {
    renderCard(
      assessment({
        pending_quiz_id: QUIZ,
        can_start: false,
        blocked_by: "quiz_pending",
        mastery: mastery(),
        last_attempt: {
          id: ATTEMPT,
          status: "graded",
          submitted_at: "2026-10-11T10:05:00Z",
          percent: 52,
        },
        recommendation: recommendation({ action: "take_quiz", quiz_id: QUIZ }),
      }),
    );

    expect(screen.getAllByRole("link", { name: /take the quiz/i })).toHaveLength(1);
    expect(screen.queryByText("Your quiz is ready")).not.toBeInTheDocument();
    expect(screen.getByText("Your next step")).toBeInTheDocument();
  });

  it("offers another quiz when the topic is known", () => {
    renderCard(
      assessment({
        mastery: mastery({ score: 95, band: "mastered" }),
        last_attempt: {
          id: ATTEMPT,
          status: "graded",
          submitted_at: "2026-10-11T10:05:00Z",
          percent: 95,
        },
      }),
    );

    expect(screen.getByText("Mastered")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Take another quiz" })).toBeInTheDocument();
  });
});

describe("TopicProgressList", () => {
  it("shows each topic's band in words, or that it has not been assessed", () => {
    render(<TopicProgressList goalId={GOAL} topics={goalProgress().topics} />);

    const items = screen.getAllByRole("listitem");
    expect(within(items[0]!).getByRole("link", { name: "Ownership" })).toHaveAttribute(
      "href",
      `/goals/${GOAL}/learn/${ITEM}`,
    );
    expect(within(items[0]!).getByText("Needs practice")).toBeInTheDocument();
    expect(within(items[0]!).getByText("52%")).toBeInTheDocument();
    expect(within(items[0]!).getByRole("link", { name: /results/i })).toBeInTheDocument();
    expect(within(items[1]!).getByText("Not assessed yet")).toBeInTheDocument();
  });

  it("says when a quiz is waiting and when a score is an early estimate", () => {
    render(
      <TopicProgressList
        goalId={GOAL}
        topics={[
          topicProgress({ mastery: mastery({ low_confidence: true }), pending_quiz_id: QUIZ }),
          topicProgress({ item_id: "other", title: "Other", study: study({ has_lesson: true }) }),
        ]}
      />,
    );

    expect(screen.getByText("Early estimate")).toBeInTheDocument();
    expect(screen.getByText("Quiz waiting")).toBeInTheDocument();
    expect(screen.getByText(/Lesson ready/)).toBeInTheDocument();
  });
});

describe("RecommendationCard", () => {
  it("links to a quiz that is already written", () => {
    render(
      <RecommendationCard
        goalId={GOAL}
        recommendation={recommendation({
          action: "take_quiz",
          quiz_id: QUIZ,
          review_lesson: false,
        })}
      />,
    );

    expect(screen.getByRole("link", { name: /take the quiz/i })).toHaveAttribute(
      "href",
      `/goals/${GOAL}/learn/${ITEM}/quiz/${QUIZ}`,
    );
  });

  it("points at the lesson to continue with", () => {
    render(
      <RecommendationCard
        goalId={GOAL}
        recommendation={recommendation({
          action: "continue_studying",
          reason: "Start “Borrowing”.",
          review_lesson: false,
          objective_texts: [],
        })}
      />,
    );

    expect(screen.getByText("Start “Borrowing”.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /continue studying/i })).toBeInTheDocument();
  });

  it("congratulates and offers nothing when everything is mastered", () => {
    render(
      <RecommendationCard
        goalId={GOAL}
        recommendation={recommendation({
          action: "all_done",
          item_id: null,
          item_title: null,
          reason: "Every topic on your roadmap is mastered.",
          review_lesson: false,
          objective_texts: [],
        })}
      />,
    );

    expect(screen.getByText("You're up to date")).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("names the step but offers no button for an archived goal", () => {
    render(<RecommendationCard goalId={GOAL} recommendation={recommendation()} readOnly />);

    expect(screen.getByText(/You scored 52%/)).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
});
