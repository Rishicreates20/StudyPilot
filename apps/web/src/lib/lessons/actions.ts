"use server";

import { notFound, redirect } from "next/navigation";

import {
  ApiError,
  cancelJob,
  retryJob,
  saveLessonProgress,
  startLesson,
  type LessonRequest,
} from "@/lib/api/server";
import { requireSession } from "@/lib/auth/action-session";
import { sessionEndedUrlFor } from "@/lib/auth/paths";
import { isGoalId } from "@/lib/goals/ids";
import { isLessonAdjust } from "@/lib/lessons/labels";
import { studyPath } from "@/lib/lessons/paths";

/**
 * Writing, cancelling and retrying a lesson, and saving the learner's place in it.
 *
 * The rules are the same as for goals and roadmaps: nothing here names an owner (the API derives
 * it from the verified token, and answers 404 for anything that is not the caller's), identifiers
 * from the browser are checked before they reach an API path, and every outcome of a form ends in
 * a redirect to a page that shows the real state. The AI call itself happens later, in the worker.
 */

const MAX_FEEDBACK_CHARS = 300;
const SECTION_ID = /^s[0-9]{1,2}$/;
const MAX_SECTIONS = 12;

/** Which notice explains why the API refused to start (or retry) a lesson. */
function noticeForRefusal(error: ApiError): string | null {
  switch (error.code) {
    case "LESSON_JOB_ACTIVE":
      return null; // the page already shows it being written
    case "LESSON_EXISTS":
      return "lesson-exists";
    case "LESSON_QUEUE_FULL":
      return "lesson-queue-full";
    case "LESSON_LIMIT_REACHED":
      return "lesson-limit";
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

function pageWithNotice(goalId: string, itemId: string, notice: string | null): string {
  const path = studyPath(goalId, itemId);
  return notice ? `${path}?notice=${notice}` : path;
}

function checkIds(...ids: string[]): void {
  if (!ids.every(isGoalId)) notFound();
}

/** The optional "what should change?" note: trimmed, and never longer than the API accepts. */
function readFeedback(formData: FormData): string | null {
  const value = formData.get("feedback");
  if (typeof value !== "string") return null;
  return value.trim().slice(0, MAX_FEEDBACK_CHARS) || null;
}

/**
 * Write the lesson for a topic, or (with `adjust`, `feedback` or `regenerate`) a new version of
 * it. Bound to the topic by the page: `generateLessonAction.bind(null, goalId, itemId)`.
 */
export async function generateLessonAction(
  goalId: string,
  itemId: string,
  formData: FormData,
): Promise<void> {
  checkIds(goalId, itemId);
  const { accessToken } = await requireSession(studyPath(goalId, itemId));

  const adjust = formData.get("adjust");
  const body: LessonRequest = {
    adjust: isLessonAdjust(adjust) ? adjust : null,
    feedback: readFeedback(formData),
    regenerate: formData.get("regenerate") === "1",
  };

  try {
    await startLesson(accessToken, itemId, body);
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    if (error.isUnauthenticated) redirect(sessionEndedUrlFor(studyPath(goalId, itemId)));
    if (error.status === 404) notFound();
    redirect(pageWithNotice(goalId, itemId, noticeForRefusal(error)));
  }

  // The study page shows the job's live progress; a banner would outlive it.
  redirect(studyPath(goalId, itemId));
}

/** Ask a queued or running lesson to stop. */
export async function cancelLessonAction(
  goalId: string,
  itemId: string,
  jobId: string,
): Promise<void> {
  checkIds(goalId, itemId, jobId);
  const { accessToken } = await requireSession(studyPath(goalId, itemId));

  try {
    await cancelJob(accessToken, jobId);
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    if (error.isUnauthenticated) redirect(sessionEndedUrlFor(studyPath(goalId, itemId)));
    if (error.status === 404) notFound();
    redirect(pageWithNotice(goalId, itemId, noticeForRefusal(error)));
  }

  redirect(pageWithNotice(goalId, itemId, "lesson-cancelled"));
}

/** Queue a fresh lesson repeating a failed one. */
export async function retryLessonAction(
  goalId: string,
  itemId: string,
  jobId: string,
): Promise<void> {
  checkIds(goalId, itemId, jobId);
  const { accessToken } = await requireSession(studyPath(goalId, itemId));

  try {
    await retryJob(accessToken, jobId);
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    if (error.isUnauthenticated) redirect(sessionEndedUrlFor(studyPath(goalId, itemId)));
    if (error.status === 404) notFound();
    redirect(pageWithNotice(goalId, itemId, noticeForRefusal(error)));
  }

  redirect(studyPath(goalId, itemId));
}

/** What the lesson reader sends to save the learner's place. */
export type ProgressInput = {
  completedSectionIds: string[];
  currentSectionId: string | null;
  completed: boolean;
};

export type SaveProgressResult =
  | { ok: true }
  /** `session`: sign in again. `archived`: the goal is read-only. `unavailable`: try again. */
  | { ok: false; reason: "session" | "archived" | "unavailable" };

/**
 * Save where the learner is in a lesson. Called from the reader as the learner reads; it returns
 * a result instead of redirecting so a failed save never throws the learner out of the lesson.
 * The API checks every section id against the lesson, whatever is sent here.
 */
export async function saveProgressAction(
  goalId: string,
  itemId: string,
  lessonId: string,
  input: ProgressInput,
): Promise<SaveProgressResult> {
  checkIds(goalId, itemId, lessonId);
  const sections = Array.isArray(input.completedSectionIds)
    ? input.completedSectionIds.filter((id) => typeof id === "string" && SECTION_ID.test(id))
    : [];
  const current =
    typeof input.currentSectionId === "string" && SECTION_ID.test(input.currentSectionId)
      ? input.currentSectionId
      : null;
  const { accessToken } = await requireSession(studyPath(goalId, itemId, lessonId));

  try {
    await saveLessonProgress(accessToken, lessonId, {
      completed_section_ids: [...new Set(sections)].slice(0, MAX_SECTIONS),
      current_section_id: current,
      completed: input.completed === true,
    });
    return { ok: true };
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    if (error.isUnauthenticated) return { ok: false, reason: "session" };
    if (error.code === "GOAL_ARCHIVED") return { ok: false, reason: "archived" };
    if (error.status === 404) notFound();
    return { ok: false, reason: "unavailable" };
  }
}
