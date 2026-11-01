"use server";

import { notFound, redirect } from "next/navigation";

import {
  ApiError,
  deleteExport,
  requestLessonExport,
  requestRoadmapExport,
  type Export,
} from "@/lib/api/server";
import { requireSession } from "@/lib/auth/action-session";
import { safeRedirectPath, sessionEndedUrlFor } from "@/lib/auth/paths";
import { isLessonFormat, isRoadmapFormat } from "@/lib/exports/labels";
import { exportsPath } from "@/lib/exports/paths";
import { noticeForExportRefusal, noticeForRequested } from "@/lib/exports/refusals";
import { isGoalId } from "@/lib/goals/ids";

/**
 * Asking for an export of a lesson or a roadmap, and deleting one.
 *
 * Nothing here names an owner: the API derives it from the verified token and answers 404 for a
 * lesson, roadmap or export that is not the caller's. The format comes from the clicked button
 * and is checked against the known formats before it reaches the API. Making the file happens
 * later, in the worker; the learner is taken to the goal's exports page to follow it.
 */

function withNotice(path: string, notice: string): string {
  return `${path}?notice=${encodeURIComponent(notice)}`;
}

async function request(
  goalId: string,
  returnTo: string,
  send: (accessToken: string) => Promise<Export>,
): Promise<never> {
  const { accessToken } = await requireSession(returnTo);
  let notice: string;
  try {
    const result = await send(accessToken);
    notice = noticeForRequested(result.status);
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    if (error.isUnauthenticated) redirect(sessionEndedUrlFor(returnTo));
    if (error.status === 404) notFound();
    redirect(withNotice(returnTo, noticeForExportRefusal(error)));
  }
  redirect(withNotice(exportsPath(goalId), notice));
}

/** Export a lesson. Bound to the goal, the lesson and the page to come back to on a refusal. */
export async function requestLessonExportAction(
  goalId: string,
  lessonId: string,
  returnTo: string,
  formData: FormData,
): Promise<void> {
  if (!isGoalId(goalId) || !isGoalId(lessonId)) notFound();
  const format = formData.get("format");
  if (!isLessonFormat(format)) notFound();
  await request(goalId, safeReturn(returnTo, goalId), (token) =>
    requestLessonExport(token, lessonId, format),
  );
}

/** Export a roadmap version. Bound to the goal, the roadmap and the page to come back to. */
export async function requestRoadmapExportAction(
  goalId: string,
  roadmapId: string,
  returnTo: string,
  formData: FormData,
): Promise<void> {
  if (!isGoalId(goalId) || !isGoalId(roadmapId)) notFound();
  const format = formData.get("format");
  if (!isRoadmapFormat(format)) notFound();
  await request(goalId, safeReturn(returnTo, goalId), (token) =>
    requestRoadmapExport(token, roadmapId, format),
  );
}

/** Delete an export and its file. */
export async function deleteExportAction(goalId: string, exportId: string): Promise<void> {
  if (!isGoalId(goalId) || !isGoalId(exportId)) notFound();
  const page = exportsPath(goalId);
  const { accessToken } = await requireSession(page);
  try {
    await deleteExport(accessToken, exportId);
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    if (error.isUnauthenticated) redirect(sessionEndedUrlFor(page));
    if (error.status === 404) notFound();
    redirect(withNotice(page, noticeForExportRefusal(error)));
  }
  redirect(withNotice(page, "export-deleted"));
}

/** The page to come back to on a refusal: only a page of this goal, never anything else. */
function safeReturn(returnTo: string, goalId: string): string {
  const prefix = `/goals/${goalId}`;
  const path = safeRedirectPath(returnTo, prefix);
  // A query or fragment of its own would swallow the notice added after it.
  if (path.includes("?") || path.includes("#")) return prefix;
  // Judge the path as a browser will follow it: `..` and `%2e%2e` segments are resolved first.
  const resolved = new URL(path, "http://studypilot.invalid").pathname;
  const inGoal = resolved === prefix || resolved.startsWith(`${prefix}/`);
  return inGoal ? resolved : prefix;
}
