"use server";

import { notFound, redirect } from "next/navigation";

import { ApiError, cancelJob, retryJob, startVideoSearch } from "@/lib/api/server";
import { requireSession } from "@/lib/auth/action-session";
import { sessionEndedUrlFor } from "@/lib/auth/paths";
import { isGoalId } from "@/lib/goals/ids";
import { studyPath } from "@/lib/lessons/paths";

/**
 * Finding, cancelling and retrying a topic's video search.
 *
 * As for lessons: nothing here names an owner (the API derives it from the verified token and
 * answers 404 for anything that is not the caller's), identifiers are checked before they reach an
 * API path, and every outcome ends in a redirect to the study page, which shows the real state.
 * The search itself happens later, in the worker.
 */

/** The study page's own anchor for the videos card, so a redirect lands next to it. */
const VIDEOS_ANCHOR = "#videos";

function noticeForRefusal(error: ApiError): string | null {
  switch (error.code) {
    case "VIDEO_SEARCH_ACTIVE":
      return null; // the page already shows it running
    case "VIDEOS_EXIST":
      return "videos-exist";
    case "VIDEO_SEARCH_LIMIT_REACHED":
      return "videos-limit";
    case "VIDEOS_NOT_CONFIGURED":
      return "videos-unavailable";
    case "GOAL_ARCHIVED":
      return "goal-archived";
    case "ROADMAP_NOT_CURRENT":
      return "roadmap-not-current";
    default:
      return error.status === 409 ? "status-conflict" : "unavailable";
  }
}

/** A notice is shown at the top of the page, so only a plain return jumps down to the card. */
function pageWithNotice(goalId: string, itemId: string, notice: string | null): string {
  const path = studyPath(goalId, itemId);
  return notice ? `${path}?notice=${notice}` : `${path}${VIDEOS_ANCHOR}`;
}

function checkIds(...ids: string[]): void {
  if (!ids.every(isGoalId)) notFound();
}

async function run(goalId: string, itemId: string, request: (token: string) => Promise<unknown>) {
  const { accessToken } = await requireSession(studyPath(goalId, itemId));
  try {
    await request(accessToken);
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    if (error.isUnauthenticated) redirect(sessionEndedUrlFor(studyPath(goalId, itemId)));
    if (error.status === 404) notFound();
    redirect(pageWithNotice(goalId, itemId, noticeForRefusal(error)));
  }
}

/**
 * Find videos for a topic; with a form field `refresh=1`, search again and replace the current
 * suggestions. Bound by the page: `findVideosAction.bind(null, goalId, itemId)`.
 */
export async function findVideosAction(
  goalId: string,
  itemId: string,
  formData: FormData,
): Promise<void> {
  checkIds(goalId, itemId);
  const refresh = formData.get("refresh") === "1";
  await run(goalId, itemId, (token) => startVideoSearch(token, itemId, refresh));
  redirect(pageWithNotice(goalId, itemId, null));
}

/** Ask a queued or running video search to stop. */
export async function cancelVideoSearchAction(
  goalId: string,
  itemId: string,
  jobId: string,
): Promise<void> {
  checkIds(goalId, itemId, jobId);
  await run(goalId, itemId, (token) => cancelJob(token, jobId));
  redirect(pageWithNotice(goalId, itemId, null));
}

/** Queue a fresh search repeating a failed one. */
export async function retryVideoSearchAction(
  goalId: string,
  itemId: string,
  jobId: string,
): Promise<void> {
  checkIds(goalId, itemId, jobId);
  await run(goalId, itemId, (token) => retryJob(token, jobId));
  redirect(pageWithNotice(goalId, itemId, null));
}
