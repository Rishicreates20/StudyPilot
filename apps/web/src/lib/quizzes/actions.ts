"use server";

import { notFound, redirect } from "next/navigation";

import {
  ApiError,
  cancelJob,
  fetchQuiz,
  regradeAttempt,
  retryJob,
  reviewAnswer,
  startQuiz,
  submitQuiz,
  type QuizDetail,
} from "@/lib/api/server";
import { requireSession } from "@/lib/auth/action-session";
import { sessionEndedUrlFor } from "@/lib/auth/paths";
import { isGoalId } from "@/lib/goals/ids";
import { studyPath } from "@/lib/lessons/paths";
import { readAnswers } from "@/lib/quizzes/answers";
import { quizPath, resultsPath } from "@/lib/quizzes/paths";

/**
 * Starting, cancelling and retrying a quiz, submitting its answers, reviewing the marking of a
 * short answer and asking for it to be marked again.
 *
 * The same rules as for lessons: nothing here names an owner (the API derives it from the verified
 * token and answers 404 for anything that is not the caller's), identifiers from the browser are
 * checked before they reach an API path, and an outcome ends in a redirect to a page that shows the
 * real state. Answers are read against the quiz's own questions as the API returns them, so a form
 * cannot add a question or an option of its own: the API checks them again whatever is sent.
 */

const POINT_ID = /^p[0-9]{1,2}$/;
const MAX_POINTS = 5;

type Purpose = "check" | "practice";

/** Which notice explains why the API refused to start (or retry) a quiz. */
function noticeForRefusal(error: ApiError): string | null {
  switch (error.code) {
    case "QUIZ_JOB_ACTIVE":
      return null; // the page already shows it being written
    case "QUIZ_PENDING":
      return "quiz-pending";
    case "LESSON_REQUIRED":
      return "lesson-required";
    case "QUIZ_LIMIT_REACHED":
      return "quiz-limit";
    case "AI_NOT_CONFIGURED":
      return "ai-unavailable";
    case "GOAL_ARCHIVED":
      return "goal-archived";
    case "ROADMAP_NOT_CURRENT":
      return "roadmap-not-current";
    case "TOPIC_NOT_LESSONABLE":
      return "not-lessonable";
    default:
      return error.status === 409 ? "status-conflict" : "unavailable";
  }
}

function withNotice(path: string, notice: string | null): string {
  return notice ? `${path}?notice=${notice}` : path;
}

function checkIds(...ids: string[]): void {
  if (!ids.every(isGoalId)) notFound();
}

function isPurpose(value: unknown): value is Purpose {
  return value === "check" || value === "practice";
}

/**
 * Write a quiz for a topic from its lesson. Bound to the topic by the page:
 * `startQuizAction.bind(null, goalId, itemId, purpose)`.
 */
export async function startQuizAction(
  goalId: string,
  itemId: string,
  purpose: Purpose,
): Promise<void> {
  checkIds(goalId, itemId);
  const page = studyPath(goalId, itemId);
  const { accessToken } = await requireSession(page);

  try {
    await startQuiz(accessToken, itemId, isPurpose(purpose) ? purpose : "check");
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    if (error.isUnauthenticated) redirect(sessionEndedUrlFor(page));
    if (error.status === 404) notFound();
    redirect(withNotice(page, noticeForRefusal(error)));
  }

  // The study page shows the job's live progress; a banner would outlive it.
  redirect(page);
}

/** Ask a queued or running quiz job to stop. */
export async function cancelQuizAction(
  goalId: string,
  itemId: string,
  jobId: string,
): Promise<void> {
  checkIds(goalId, itemId, jobId);
  const page = studyPath(goalId, itemId);
  const { accessToken } = await requireSession(page);

  try {
    await cancelJob(accessToken, jobId);
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    if (error.isUnauthenticated) redirect(sessionEndedUrlFor(page));
    if (error.status === 404) notFound();
    redirect(withNotice(page, noticeForRefusal(error)));
  }

  redirect(withNotice(page, "quiz-cancelled"));
}

/** Ask a queued or running marking job to stop; the short answers stay waiting. */
export async function cancelMarkingAction(
  goalId: string,
  itemId: string,
  attemptId: string,
  jobId: string,
): Promise<void> {
  checkIds(goalId, itemId, attemptId, jobId);
  const page = resultsPath(goalId, itemId, attemptId);
  const { accessToken } = await requireSession(page);

  try {
    await cancelJob(accessToken, jobId);
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    if (error.isUnauthenticated) redirect(sessionEndedUrlFor(page));
    if (error.status === 404) notFound();
    redirect(withNotice(page, "unavailable"));
  }

  redirect(withNotice(page, "marking-cancelled"));
}

/** Queue a fresh quiz repeating a failed one. */
export async function retryQuizAction(
  goalId: string,
  itemId: string,
  jobId: string,
): Promise<void> {
  checkIds(goalId, itemId, jobId);
  const page = studyPath(goalId, itemId);
  const { accessToken } = await requireSession(page);

  try {
    await retryJob(accessToken, jobId);
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    if (error.isUnauthenticated) redirect(sessionEndedUrlFor(page));
    if (error.status === 404) notFound();
    redirect(withNotice(page, noticeForRefusal(error)));
  }

  redirect(page);
}

/**
 * Submit a quiz. Reads the quiz first (a 404 here is a missing or someone else's quiz), then sends
 * the answers. A quiz that was already submitted, in another tab or by a double click, leads to the
 * results of that submission rather than an error.
 */
export async function submitQuizAction(
  goalId: string,
  itemId: string,
  quizId: string,
  formData: FormData,
): Promise<void> {
  checkIds(goalId, itemId, quizId);
  const page = quizPath(goalId, itemId, quizId);
  const { accessToken } = await requireSession(page);

  let quiz: QuizDetail;
  try {
    quiz = await fetchQuiz(accessToken, quizId);
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    if (error.isUnauthenticated) redirect(sessionEndedUrlFor(page));
    if (error.status === 404) notFound();
    redirect(withNotice(page, "unavailable"));
  }
  if (quiz.goal_id !== goalId || quiz.item_id !== itemId) notFound();
  if (quiz.attempt) redirect(resultsPath(goalId, itemId, quiz.attempt.id));

  try {
    const result = await submitQuiz(accessToken, quizId, { answers: readAnswers(quiz, formData) });
    redirect(resultsPath(goalId, itemId, result.id));
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    if (error.isUnauthenticated) redirect(sessionEndedUrlFor(page));
    if (error.status === 404) notFound();
    if (error.code === "QUIZ_ALREADY_SUBMITTED") {
      // Submitted from another window a moment ago: show those results.
      const again = await fetchQuiz(accessToken, quizId).catch(() => null);
      if (again?.attempt) redirect(resultsPath(goalId, itemId, again.attempt.id));
      redirect(withNotice(page, "already-submitted"));
    }
    if (error.code === "GOAL_ARCHIVED") redirect(withNotice(page, "goal-archived"));
    redirect(withNotice(page, error.status === 422 ? "answers-invalid" : "unavailable"));
  }
}

/**
 * Record the learner's own review of a short answer: which rubric points their answer covered.
 * Bound by the results page: `reviewAnswerAction.bind(null, goalId, itemId, attemptId, answerId)`.
 */
export async function reviewAnswerAction(
  goalId: string,
  itemId: string,
  attemptId: string,
  answerId: string,
  formData: FormData,
): Promise<void> {
  checkIds(goalId, itemId, attemptId, answerId);
  const page = resultsPath(goalId, itemId, attemptId);
  const { accessToken } = await requireSession(page);

  const met = formData
    .getAll("met")
    .filter((value): value is string => typeof value === "string" && POINT_ID.test(value));

  try {
    await reviewAnswer(accessToken, answerId, [...new Set(met)].slice(0, MAX_POINTS));
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    if (error.isUnauthenticated) redirect(sessionEndedUrlFor(page));
    if (error.status === 404) notFound();
    if (error.code === "GOAL_ARCHIVED") redirect(withNotice(page, "goal-archived"));
    redirect(withNotice(page, error.status === 409 ? "not-reviewable" : "unavailable"));
  }

  redirect(withNotice(page, "reviewed"));
}

/** Ask for the short answers of an attempt to be marked again after marking failed. */
export async function regradeAction(
  goalId: string,
  itemId: string,
  attemptId: string,
): Promise<void> {
  checkIds(goalId, itemId, attemptId);
  const page = resultsPath(goalId, itemId, attemptId);
  const { accessToken } = await requireSession(page);

  try {
    await regradeAttempt(accessToken, attemptId);
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    if (error.isUnauthenticated) redirect(sessionEndedUrlFor(page));
    if (error.status === 404) notFound();
    if (error.code === "GRADING_RETRIES_EXHAUSTED") redirect(withNotice(page, "marking-exhausted"));
    if (error.code === "GRADING_ACTIVE") redirect(page);
    if (error.code === "GOAL_ARCHIVED") redirect(withNotice(page, "goal-archived"));
    redirect(withNotice(page, error.status === 409 ? "status-conflict" : "unavailable"));
  }

  redirect(page);
}
