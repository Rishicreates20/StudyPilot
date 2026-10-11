"use server";

import { notFound, redirect } from "next/navigation";

import { ApiError, cancelJob, makeRoadmapCurrent, retryJob, startRoadmap } from "@/lib/api/server";
import { requireSession } from "@/lib/auth/action-session";
import { sessionEndedUrlFor } from "@/lib/auth/paths";
import { goalPath, isGoalId } from "@/lib/goals/ids";
import { roadmapPath } from "@/lib/roadmaps/paths";

/**
 * Starting, cancelling and retrying a roadmap generation, and switching versions.
 *
 * The rules are the same as for goals: nothing here names an owner (the API derives it from the
 * verified token, and answers 404 for anything that is not the caller's), identifiers from the
 * browser are checked before they reach an API path, and every outcome ends in a redirect to a
 * page that shows the real state. The AI call itself happens later, in the worker.
 */

const MAX_FEEDBACK_CHARS = 500;

/** Which notice explains why the API refused to start (or retry) a generation. */
function noticeForRefusal(error: ApiError): string {
  switch (error.code) {
    case "ROADMAP_JOB_ACTIVE":
      return "already-generating";
    case "GOAL_NOT_PLANNABLE":
      return "needs-detail";
    case "AI_NOT_CONFIGURED":
      return "ai-unavailable";
    case "GENERATION_LIMIT_REACHED":
      return "generation-limit";
    case "GOAL_ARCHIVED":
      return "goal-archived";
    default:
      return error.status === 409 ? "status-conflict" : "unavailable";
  }
}

/** The optional "what should change?" note: trimmed, and never longer than the API accepts. */
function readFeedback(formData: FormData): string | null {
  const value = formData.get("feedback");
  if (typeof value !== "string") return null;
  return value.trim().slice(0, MAX_FEEDBACK_CHARS) || null;
}

/**
 * Generate a roadmap for a goal, or (with a "feedback" field) revise the current one. Bound to the
 * goal by the page: `generateRoadmapAction.bind(null, goalId)`. Either way a new version is
 * stored when the job completes; earlier versions are kept.
 */
export async function generateRoadmapAction(goalId: string, formData: FormData): Promise<void> {
  if (!isGoalId(goalId)) notFound();
  const { accessToken } = await requireSession(goalPath(goalId));

  try {
    await startRoadmap(accessToken, goalId, { feedback: readFeedback(formData) });
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    if (error.isUnauthenticated) redirect(sessionEndedUrlFor(goalPath(goalId)));
    if (error.status === 404) notFound();
    redirect(`${goalPath(goalId)}?notice=${noticeForRefusal(error)}`);
  }

  // The goal page shows the job's live progress; a banner would outlive it.
  redirect(goalPath(goalId));
}

/** Ask a queued or running generation to stop. */
export async function cancelGenerationAction(goalId: string, jobId: string): Promise<void> {
  if (!isGoalId(goalId) || !isGoalId(jobId)) notFound();
  const { accessToken } = await requireSession(goalPath(goalId));

  try {
    await cancelJob(accessToken, jobId);
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    if (error.isUnauthenticated) redirect(sessionEndedUrlFor(goalPath(goalId)));
    if (error.status === 404) notFound();
    redirect(`${goalPath(goalId)}?notice=${noticeForRefusal(error)}`);
  }

  redirect(`${goalPath(goalId)}?notice=generation-cancelled`);
}

/** Queue a fresh generation repeating a failed one. */
export async function retryGenerationAction(goalId: string, jobId: string): Promise<void> {
  if (!isGoalId(goalId) || !isGoalId(jobId)) notFound();
  const { accessToken } = await requireSession(goalPath(goalId));

  try {
    await retryJob(accessToken, jobId);
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    if (error.isUnauthenticated) redirect(sessionEndedUrlFor(goalPath(goalId)));
    if (error.status === 404) notFound();
    redirect(`${goalPath(goalId)}?notice=${noticeForRefusal(error)}`);
  }

  // The goal page shows the job's live progress; a banner would outlive it.
  redirect(goalPath(goalId));
}

/** Make another version the goal's current roadmap. Nothing is deleted. */
export async function makeRoadmapCurrentAction(goalId: string, roadmapId: string): Promise<void> {
  if (!isGoalId(goalId) || !isGoalId(roadmapId)) notFound();
  const { accessToken } = await requireSession(roadmapPath(goalId));

  try {
    await makeRoadmapCurrent(accessToken, roadmapId);
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    if (error.isUnauthenticated) redirect(sessionEndedUrlFor(roadmapPath(goalId)));
    if (error.status === 404) notFound();
    redirect(`${roadmapPath(goalId)}?notice=${noticeForRefusal(error)}`);
  }

  redirect(`${roadmapPath(goalId)}?notice=version-switched`);
}
