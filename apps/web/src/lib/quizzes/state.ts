import type {
  AnswerResult,
  AttemptResult,
  GenerationJob,
  GoalProgress,
  QuestionOut,
  Recommendation,
  TopicAssessment,
  TopicProgress,
} from "@/lib/api/server";
import { quizPath } from "@/lib/quizzes/paths";
import { studyPath } from "@/lib/lessons/paths";

const ACTIVE = new Set<GenerationJob["status"]>(["queued", "running"]);

/** What the topic's quiz card shows. */
export type AssessmentCardState =
  /** A quiz cannot be started, and the card says why. */
  | { kind: "blocked"; reason: NonNullable<TopicAssessment["blocked_by"]> }
  /** A quiz is being written. */
  | { kind: "writing"; job: GenerationJob }
  /** A quiz is written and waiting to be taken. */
  | { kind: "ready"; quizId: string }
  /** The last attempt to write a quiz failed. */
  | { kind: "failed"; job: GenerationJob }
  /** Nothing waiting: a quiz can be started. */
  | { kind: "idle" };

/**
 * Decides the quiz card from the topic's assessment. A quiz being written or waiting always wins
 * over a start button (there is only ever one untaken quiz per topic), then a failure with a way to
 * retry, then the invitation to start one.
 */
export function assessmentCardState(assessment: TopicAssessment): AssessmentCardState {
  const { job, pending_quiz_id: pending, blocked_by: blocked } = assessment;
  if (job && ACTIVE.has(job.status)) return { kind: "writing", job };
  if (pending) return { kind: "ready", quizId: pending };
  if (blocked) return { kind: "blocked", reason: blocked };
  if (job?.status === "failed") return { kind: "failed", job };
  return { kind: "idle" };
}

const BLOCK_TEXT: Readonly<Record<NonNullable<TopicAssessment["blocked_by"]>, string>> = {
  lesson_required: "Study this topic's lesson first: the quiz is written from it.",
  quiz_pending: "A quiz is waiting for you.",
  quiz_in_progress: "A quiz is being written.",
  roadmap_not_current:
    "This topic belongs to an earlier roadmap version, so new quizzes are only written for the current one.",
  goal_archived: "This goal is archived. Restore it to take quizzes.",
};

export function blockedText(reason: NonNullable<TopicAssessment["blocked_by"]>): string {
  return BLOCK_TEXT[reason];
}

/** How many questions of a quiz the learner has answered, from the submitted form. */
export function countAnswered(
  questions: readonly Pick<QuestionOut, "id" | "kind">[],
  values: ReadonlyMap<string, string>,
): number {
  return questions.filter((question) => (values.get(question.id) ?? "").trim() !== "").length;
}

/** Where a recommendation leads, and what its button says. */
export type RecommendationTarget =
  | { kind: "link"; href: string; label: string }
  /** Starts a quiz right away (a form that posts to a Server Action). */
  | { kind: "start-quiz"; itemId: string; purpose: "check" | "practice"; label: string }
  | { kind: "none" };

/**
 * The control that carries out a recommended next step. A written quiz is taken from its page, a
 * quiz still to be written is started from here, studying goes to the lesson, and "all done" has
 * nothing to press.
 */
export function recommendationTarget(
  goalId: string,
  recommendation: Recommendation,
): RecommendationTarget {
  const itemId = recommendation.item_id;
  switch (recommendation.action) {
    case "take_quiz":
      if (itemId && recommendation.quiz_id) {
        return {
          kind: "link",
          href: quizPath(goalId, itemId, recommendation.quiz_id),
          label: "Take the quiz",
        };
      }
      return itemId
        ? { kind: "start-quiz", itemId, purpose: "check", label: "Take a quiz" }
        : { kind: "none" };
    case "practice_quiz":
      return itemId
        ? { kind: "start-quiz", itemId, purpose: "practice", label: "Practise these parts" }
        : { kind: "none" };
    case "continue_studying":
      return itemId
        ? { kind: "link", href: studyPath(goalId, itemId), label: "Continue studying" }
        : { kind: "none" };
    case "all_done":
      return { kind: "none" };
  }
}

/** Topics that need practice, weakest first (the order the API already uses). */
export function weakTopics(progress: Pick<GoalProgress, "topics">): TopicProgress[] {
  return progress.topics
    .filter((topic) => topic.mastery?.band === "needs_practice")
    .sort((a, b) => (a.mastery?.score ?? 0) - (b.mastery?.score ?? 0));
}

/** The answers of a result in which the learner lost points, worth reading first. */
export function missedAnswers(result: Pick<AttemptResult, "answers">): AnswerResult[] {
  return result.answers.filter(
    (answer) => answer.points_awarded !== null && answer.points_awarded < answer.max_points,
  );
}

/** Objectives with a low score in this result's topic, weakest first. */
export function weakObjectives(
  result: Pick<AttemptResult, "mastery">,
): NonNullable<AttemptResult["mastery"]>["objectives"] {
  const mastery = result.mastery;
  if (!mastery) return [];
  return mastery.objectives
    .filter((objective) => objective.score < mastery.needs_practice_below)
    .sort((a, b) => a.score - b.score);
}
