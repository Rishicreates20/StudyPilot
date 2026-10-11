import type {
  AnswerResult,
  AttemptResult,
  GoalProgress,
  QuizDetail,
  Recommendation,
  TopicAssessment,
  TopicMastery,
  TopicProgress,
} from "@/lib/api/server";
import { GOAL, ITEM, JOB, NEXT_ITEM, lessonJob, study } from "@/test-support/lessons";

export const QUIZ = "88888888-8888-4888-8888-888888888888";
export const ATTEMPT = "99999999-9999-4999-8999-999999999999";
export const Q1 = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1";
export const Q2 = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa2";
export const Q3 = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa3";
export const A1 = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1";
export const A2 = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2";
export const A3 = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb3";

export function quiz(overrides: Partial<QuizDetail> = {}): QuizDetail {
  return {
    id: QUIZ,
    goal_id: GOAL,
    item_id: ITEM,
    item_title: "Ownership",
    lesson_id: "44444444-4444-4444-8444-444444444444",
    purpose: "check",
    title: "Check your understanding of ownership",
    question_count: 3,
    is_synthetic: false,
    created_at: "2026-10-11T10:00:00Z",
    status: "ready",
    attempt: null,
    language: "en",
    focus_objective_ids: [],
    objectives: [
      { id: "o1", text: "Explain what ownership means" },
      { id: "o2", text: "Use references to borrow a value" },
    ],
    questions: [
      {
        id: Q1,
        position: 1,
        kind: "multiple_choice",
        prompt: "What happens to a value when its owner goes out of scope?",
        options: [
          { id: "a", text: "It is dropped" },
          { id: "b", text: "It is copied" },
          { id: "c", text: "It is leaked" },
          { id: "d", text: "It moves to the heap" },
        ],
        objective_id: "o1",
        objective_text: "Explain what ownership means",
        difficulty: "easy",
        max_points: 1,
      },
      {
        id: Q2,
        position: 2,
        kind: "true_false",
        prompt: "A shared reference lets you change the value it points to.",
        options: [
          { id: "true", text: "True" },
          { id: "false", text: "False" },
        ],
        objective_id: "o2",
        objective_text: "Use references to borrow a value",
        difficulty: "medium",
        max_points: 2,
      },
      {
        id: Q3,
        position: 3,
        kind: "short_answer",
        prompt: "In your own words, why does Rust have an ownership system?",
        options: null,
        objective_id: "o1",
        objective_text: "Explain what ownership means",
        difficulty: "hard",
        max_points: 3,
      },
    ],
    ...overrides,
  };
}

export function mastery(overrides: Partial<TopicMastery> = {}): TopicMastery {
  return {
    item_id: ITEM,
    score: 52,
    band: "needs_practice",
    attempts_count: 1,
    answers_count: 5,
    low_confidence: false,
    objectives: [
      { id: "o1", text: "Explain what ownership means", score: 80, answers: 3 },
      { id: "o2", text: "Use references to borrow a value", score: 20, answers: 2 },
    ],
    computed_at: "2026-10-11T10:10:00Z",
    algorithm_version: "weighted-recency/v1",
    needs_practice_below: 70,
    mastered_from: 90,
    ...overrides,
  };
}

export function recommendation(overrides: Partial<Recommendation> = {}): Recommendation {
  return {
    action: "practice_quiz",
    reason:
      "You scored 52% on “Ownership”. Go over the lesson again, then take a short practice quiz.",
    item_id: ITEM,
    item_title: "Ownership",
    quiz_id: null,
    objective_ids: ["o2"],
    objective_texts: ["Use references to borrow a value"],
    review_lesson: true,
    ...overrides,
  };
}

export function answer(overrides: Partial<AnswerResult> = {}): AnswerResult {
  return {
    id: A1,
    question_id: Q1,
    position: 1,
    kind: "multiple_choice",
    prompt: "What happens to a value when its owner goes out of scope?",
    options: [
      { id: "a", text: "It is dropped" },
      { id: "b", text: "It is copied" },
    ],
    objective_id: "o1",
    objective_text: "Explain what ownership means",
    difficulty: "easy",
    your_answer: { option_id: "b", text: null },
    skipped: false,
    is_correct: false,
    points_awarded: 0,
    max_points: 1,
    grading_method: "deterministic",
    feedback: {
      explanation: "The owner's scope ends, so Rust drops the value.",
      correct_option_id: "a",
      option_notes: {
        a: "Right: drop runs at the end of scope.",
        b: "Copying is not what happens.",
      },
      rubric: null,
      model_answer: null,
      matched_point_ids: [],
      comment: null,
    },
    ...overrides,
  };
}

export function shortAnswer(overrides: Partial<AnswerResult> = {}): AnswerResult {
  return answer({
    id: A3,
    question_id: Q3,
    position: 3,
    kind: "short_answer",
    prompt: "In your own words, why does Rust have an ownership system?",
    options: null,
    difficulty: "hard",
    your_answer: { option_id: null, text: "To manage memory without a garbage collector." },
    is_correct: null,
    points_awarded: 1.5,
    max_points: 3,
    grading_method: "ai_estimate",
    feedback: {
      explanation: "Ownership gives memory safety without a collector.",
      correct_option_id: null,
      option_notes: {},
      rubric: [
        { id: "p1", text: "Says it manages memory", points: 1 },
        { id: "p2", text: "Says it avoids a garbage collector", points: 1 },
      ],
      model_answer: "It frees memory safely at compile time, with no garbage collector.",
      matched_point_ids: ["p1"],
      comment: "You covered memory management; mention the missing collector.",
    },
    ...overrides,
  });
}

export function result(overrides: Partial<AttemptResult> = {}): AttemptResult {
  return {
    id: ATTEMPT,
    quiz_id: QUIZ,
    goal_id: GOAL,
    item_id: ITEM,
    item_title: "Ownership",
    quiz_title: "Check your understanding of ownership",
    purpose: "check",
    status: "graded",
    submitted_at: "2026-10-11T10:05:00Z",
    graded_at: "2026-10-11T10:05:05Z",
    points_earned: 1.5,
    points_possible: 6,
    percent: 25,
    pending_answers: 0,
    grading_job: null,
    is_synthetic: false,
    answers: [answer(), shortAnswer()],
    mastery: mastery({ score: 25 }),
    recommendation: recommendation(),
    ...overrides,
  };
}

export function assessment(overrides: Partial<TopicAssessment> = {}): TopicAssessment {
  return {
    item_id: ITEM,
    mastery: null,
    pending_quiz_id: null,
    last_attempt: null,
    job: null,
    can_start: true,
    blocked_by: null,
    recommendation: null,
    ...overrides,
  };
}

export function quizJob(overrides: Partial<ReturnType<typeof lessonJob>> = {}) {
  return lessonJob({ id: JOB, job_type: "quiz", stage: "writing", ...overrides });
}

export function topicProgress(overrides: Partial<TopicProgress> = {}): TopicProgress {
  return {
    item_id: ITEM,
    title: "Ownership",
    module_title: "Core ideas",
    kind: "topic",
    study: study({ status: "completed", has_lesson: true, sections_done: 3, sections_total: 3 }),
    mastery: null,
    pending_quiz_id: null,
    last_attempt: null,
    ...overrides,
  };
}

export function goalProgress(overrides: Partial<GoalProgress> = {}): GoalProgress {
  return {
    goal_id: GOAL,
    roadmap_id: "77777777-7777-4777-8777-777777777777",
    topics: [
      topicProgress({
        mastery: mastery(),
        last_attempt: {
          id: ATTEMPT,
          status: "graded",
          submitted_at: "2026-10-11T10:05:00Z",
          percent: 52,
        },
      }),
      topicProgress({ item_id: NEXT_ITEM, title: "Borrowing", study: study() }),
    ],
    counts: { total: 2, mastered: 0, progressing: 0, needs_practice: 1, not_assessed: 1 },
    recommendation: recommendation(),
    ...overrides,
  };
}
