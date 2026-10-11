// @vitest-environment node
import { describe, expect, it } from "vitest";

import type { TopicAssessment } from "@/lib/api/server";
import { answerField, MAX_ANSWER_CHARS, readAnswers } from "@/lib/quizzes/answers";
import {
  bandExplanation,
  bandLabel,
  bandVariant,
  describeGradingStage,
  describeQuizStage,
  formatPercent,
  formatPoints,
  gradingMethodLabel,
  pointsLabel,
} from "@/lib/quizzes/labels";
import { quizPath, resultsPath } from "@/lib/quizzes/paths";
import {
  assessmentCardState,
  countAnswered,
  missedAnswers,
  recommendationTarget,
  weakObjectives,
  weakTopics,
} from "@/lib/quizzes/state";
import { GOAL, ITEM } from "@/test-support/lessons";
import {
  A1,
  answer,
  assessment,
  ATTEMPT,
  goalProgress,
  mastery,
  Q1,
  Q2,
  Q3,
  QUIZ,
  quiz,
  quizJob,
  recommendation,
  result,
  shortAnswer,
  topicProgress,
} from "@/test-support/quizzes";

function form(fields: Record<string, string>): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(fields)) data.append(key, value);
  return data;
}

describe("paths", () => {
  it("nest the quiz and its results under the topic", () => {
    expect(quizPath(GOAL, ITEM, QUIZ)).toBe(`/goals/${GOAL}/learn/${ITEM}/quiz/${QUIZ}`);
    expect(resultsPath(GOAL, ITEM, ATTEMPT)).toBe(
      `/goals/${GOAL}/learn/${ITEM}/results/${ATTEMPT}`,
    );
  });
});

describe("labels", () => {
  it("names every mastery band in words and gives it a badge colour", () => {
    expect(bandLabel("needs_practice")).toBe("Needs practice");
    expect(bandLabel("progressing")).toBe("Getting there");
    expect(bandLabel("mastered")).toBe("Mastered");
    expect(bandVariant("needs_practice")).toBe("warning");
    expect(bandVariant("mastered")).toBe("success");
  });

  it("explains a band with the thresholds that decided it", () => {
    const limits = { needs_practice_below: 70, mastered_from: 90 };
    expect(bandExplanation("needs_practice", limits)).toContain("Below 70%");
    expect(bandExplanation("progressing", limits)).toContain("Between 70% and 90%");
    expect(bandExplanation("mastered", limits)).toContain("90% or more");
  });

  it("rounds scores to whole percentages and keeps part points readable", () => {
    expect(formatPercent(52.4)).toBe("52%");
    expect(formatPercent(99.6)).toBe("100%");
    expect(formatPoints(2)).toBe("2");
    expect(formatPoints(1.5)).toBe("1.5");
    expect(formatPoints(0.333)).toBe("0.3");
    expect(pointsLabel(1)).toBe("1 point");
    expect(pointsLabel(3)).toBe("3 points");
  });

  it("says plainly how an answer was marked", () => {
    expect(gradingMethodLabel("deterministic")).toBe("Marked automatically");
    expect(gradingMethodLabel("ai_estimate")).toBe("AI estimate");
    expect(gradingMethodLabel("self_review")).toBe("Marked by you");
    expect(gradingMethodLabel("pending")).toBe("Waiting to be marked");
  });

  it("describes the stages of a quiz job and of a marking job", () => {
    expect(describeQuizStage({ status: "queued", stage: "queued" })).toContain("Waiting");
    expect(describeQuizStage({ status: "running", stage: "writing" })).toContain("questions");
    expect(describeQuizStage({ status: "running", stage: "weird" })).toBe("Working on it…");
    expect(describeGradingStage({ status: "running", stage: "grading" })).toContain("rubric");
  });
});

describe("assessmentCardState", () => {
  it("shows a quiz being written before anything else", () => {
    const job = quizJob({ status: "running" });
    expect(assessmentCardState(assessment({ job, pending_quiz_id: QUIZ }))).toEqual({
      kind: "writing",
      job,
    });
  });

  it("offers a waiting quiz next", () => {
    expect(
      assessmentCardState(assessment({ pending_quiz_id: QUIZ, blocked_by: "quiz_pending" })),
    ).toEqual({
      kind: "ready",
      quizId: QUIZ,
    });
  });

  it.each<NonNullable<TopicAssessment["blocked_by"]>>([
    "lesson_required",
    "roadmap_not_current",
    "goal_archived",
  ])("explains why a quiz cannot start (%s)", (reason) => {
    expect(assessmentCardState(assessment({ can_start: false, blocked_by: reason }))).toEqual({
      kind: "blocked",
      reason,
    });
  });

  it("reports a failed attempt with a way to retry, and otherwise lets a quiz be started", () => {
    const failed = quizJob({ status: "failed", error_message: "x" });
    expect(assessmentCardState(assessment({ job: failed }))).toEqual({
      kind: "failed",
      job: failed,
    });
    expect(assessmentCardState(assessment({ job: quizJob({ status: "completed" }) }))).toEqual({
      kind: "idle",
    });
    expect(assessmentCardState(assessment())).toEqual({ kind: "idle" });
  });
});

describe("recommendationTarget", () => {
  it("takes a written quiz from its page", () => {
    expect(
      recommendationTarget(GOAL, recommendation({ action: "take_quiz", quiz_id: QUIZ })),
    ).toEqual({ kind: "link", href: quizPath(GOAL, ITEM, QUIZ), label: "Take the quiz" });
  });

  it("starts a quiz that is not written yet, and a practice quiz for weak topics", () => {
    expect(
      recommendationTarget(GOAL, recommendation({ action: "take_quiz", quiz_id: null })),
    ).toMatchObject({ kind: "start-quiz", itemId: ITEM, purpose: "check" });
    expect(recommendationTarget(GOAL, recommendation({ action: "practice_quiz" }))).toMatchObject({
      kind: "start-quiz",
      purpose: "practice",
    });
  });

  it("sends studying to the lesson and offers nothing when everything is done", () => {
    expect(
      recommendationTarget(GOAL, recommendation({ action: "continue_studying" })),
    ).toMatchObject({ kind: "link", href: `/goals/${GOAL}/learn/${ITEM}` });
    expect(
      recommendationTarget(GOAL, recommendation({ action: "all_done", item_id: null })),
    ).toEqual({ kind: "none" });
    expect(
      recommendationTarget(GOAL, recommendation({ action: "practice_quiz", item_id: null })),
    ).toEqual({ kind: "none" });
  });
});

describe("what a result highlights", () => {
  it("lists the weak topics weakest first", () => {
    const progress = goalProgress({
      topics: [
        topicProgress({ item_id: "t1", title: "A", mastery: mastery({ score: 60 }) }),
        topicProgress({ item_id: "t2", title: "B", mastery: mastery({ score: 30 }) }),
        topicProgress({
          item_id: "t3",
          title: "C",
          mastery: mastery({ score: 95, band: "mastered" }),
        }),
        topicProgress({ item_id: "t4", title: "D" }),
      ],
    });

    expect(weakTopics(progress).map((topic) => topic.title)).toEqual(["B", "A"]);
  });

  it("lists the answers that lost points, and only those the marker has scored", () => {
    const full = answer({ id: "x", points_awarded: 1, max_points: 1, is_correct: true });
    const pending = shortAnswer({ id: "y", points_awarded: null, grading_method: "pending" });
    const partial = shortAnswer({ id: "z" });

    expect(
      missedAnswers(result({ answers: [full, pending, partial, answer({ id: "w" })] })).map(
        (a) => a.id,
      ),
    ).toEqual(["z", "w"]);
  });

  it("lists the weak objectives of the topic, weakest first", () => {
    expect(weakObjectives(result({ mastery: null }))).toEqual([]);
    const weak = weakObjectives(
      result({
        mastery: mastery({
          objectives: [
            { id: "o1", text: "A", score: 65, answers: 1 },
            { id: "o2", text: "B", score: 10, answers: 1 },
            { id: "o3", text: "C", score: 90, answers: 1 },
          ],
        }),
      }),
    );
    expect(weak.map((objective) => objective.id)).toEqual(["o2", "o1"]);
  });
});

describe("countAnswered", () => {
  it("counts the questions that have a non-blank value", () => {
    const questions = quiz().questions;
    const values = new Map([
      [Q1, "a"],
      [Q2, ""],
      [Q3, "   "],
    ]);
    expect(countAnswered(questions, values)).toBe(1);
    expect(countAnswered(questions, new Map())).toBe(0);
  });
});

describe("readAnswers", () => {
  it("reads an option for choice questions and trimmed text for short answers", () => {
    const answers = readAnswers(
      quiz(),
      form({
        [answerField(Q1)]: "b",
        [answerField(Q2)]: "true",
        [answerField(Q3)]: "  my words  ",
      }),
    );

    expect(answers).toEqual([
      { question_id: Q1, option_id: "b" },
      { question_id: Q2, option_id: "true" },
      { question_id: Q3, text: "my words" },
    ]);
  });

  it("skips questions that were left blank", () => {
    expect(readAnswers(quiz(), form({ [answerField(Q3)]: "   " }))).toEqual([]);
    expect(readAnswers(quiz(), form({}))).toEqual([]);
  });

  it("ignores anything that is not one of the quiz's own questions", () => {
    const answers = readAnswers(
      quiz(),
      form({
        [answerField(Q1)]: "a",
        q_not_a_question: "a",
        question_id: Q2,
        user_id: "someone-else",
        is_correct: "true",
        points: "9",
      }),
    );

    expect(answers).toEqual([{ question_id: Q1, option_id: "a" }]);
  });

  it.each(["A", "a b", "a;drop table", "../x", "toolongoption", ""])(
    "drops the malformed option id %j instead of sending it",
    (value) => {
      expect(readAnswers(quiz(), form({ [answerField(Q1)]: value }))).toEqual([]);
    },
  );

  it("never sends more text than the API accepts", () => {
    const [sent] = readAnswers(quiz(), form({ [answerField(Q3)]: "x".repeat(5000) }));

    expect((sent as { text: string }).text).toHaveLength(MAX_ANSWER_CHARS);
  });

  it("never turns a short answer into an option or an option into text", () => {
    const answers = readAnswers(
      quiz(),
      form({ [answerField(Q3)]: "a", [answerField(Q1)]: "free text here" }),
    );

    expect(answers).toEqual([{ question_id: Q3, text: "a" }]);
  });
});

it("fixtures keep the answer out of the quiz a learner takes", () => {
  expect(JSON.stringify(quiz())).not.toMatch(/correct_option|explanation|rubric|model_answer/);
  expect(answer().id).toBe(A1);
});
