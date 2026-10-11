"use server";

import { notFound, redirect } from "next/navigation";

import { failureMessage } from "@/lib/api/failure";
import { ApiError, createGoal, deleteGoal, setGoalStatus, updateGoal } from "@/lib/api/server";
import { DASHBOARD_PATH, sessionEndedUrlFor, signInUrlFor } from "@/lib/auth/paths";
import { getAccessToken, getSessionUser } from "@/lib/auth/session";
import { zodFieldErrors } from "@/lib/forms";
import { editGoalPath, goalPath, isGoalId, isGoalStatus } from "@/lib/goals/ids";
import {
  goalFormSchema,
  mapApiFieldErrors,
  readGoalFormValues,
  toCreateBody,
  toUpdateBody,
  type GoalFormState,
} from "@/lib/goals/schema";

const NEW_GOAL_PATH = "/goals/new";
const ARCHIVED_PATH = "/goals/archived";

/**
 * Every action here follows the same rules:
 *
 * - the owner is never part of a request: the API derives it from the access token it verifies,
 *   so a tampered form or bound argument cannot act on someone else's goal (the API answers 404);
 * - IDs and statuses that come from the browser are checked before they reach an API path;
 * - session checks only decide where to send the visitor; the API is the security boundary.
 */

/** Creates a goal for the signed-in user. */
export async function createGoalAction(
  _previous: GoalFormState,
  formData: FormData,
): Promise<GoalFormState> {
  const values = readGoalFormValues(formData);
  const parsed = goalFormSchema.safeParse(values);
  if (!parsed.success) {
    return { status: "error", fieldErrors: zodFieldErrors(parsed.error), values };
  }

  const user = await getSessionUser();
  const accessToken = user ? await getAccessToken() : null;
  if (!accessToken) redirect(signInUrlFor(NEW_GOAL_PATH));

  try {
    await createGoal(accessToken, toCreateBody(parsed.data));
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    // The API rejected the token (expired, revoked, account deleted): sign in again.
    if (error.isUnauthenticated) redirect(sessionEndedUrlFor(NEW_GOAL_PATH));
    return {
      status: "error",
      formError: failureMessage(error, "goal"),
      fieldErrors: mapApiFieldErrors(error.fieldErrors),
      values,
    };
  }

  redirect(`${DASHBOARD_PATH}?notice=created`);
}

/** Saves the edit form. Bound to the goal's ID by the page: `updateGoalAction.bind(null, id)`. */
export async function updateGoalAction(
  goalId: string,
  _previous: GoalFormState,
  formData: FormData,
): Promise<GoalFormState> {
  if (!isGoalId(goalId)) notFound();
  const values = readGoalFormValues(formData);
  const parsed = goalFormSchema.safeParse(values);
  if (!parsed.success) {
    return { status: "error", fieldErrors: zodFieldErrors(parsed.error), values };
  }

  const user = await getSessionUser();
  const accessToken = user ? await getAccessToken() : null;
  if (!accessToken) redirect(signInUrlFor(editGoalPath(goalId)));

  try {
    await updateGoal(accessToken, goalId, toUpdateBody(parsed.data));
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    if (error.isUnauthenticated) redirect(sessionEndedUrlFor(editGoalPath(goalId)));
    if (error.status === 404) notFound();
    return {
      status: "error",
      formError: failureMessage(error, "changes"),
      fieldErrors: mapApiFieldErrors(error.fieldErrors),
      values,
    };
  }

  redirect(`${goalPath(goalId)}?notice=updated`);
}

/** Maps an API refusal of a status change or a delete to the notice the goal page should show. */
function noticeForRefusal(error: ApiError): string {
  if (error.code === "GOAL_LIMIT_REACHED") return "limit-reached";
  if (error.code === "GOAL_NOT_ARCHIVED") return "not-archived";
  if (error.status === 409) return "status-conflict";
  return "unavailable";
}

/**
 * Pause, resume, complete, reopen, archive or restore. Bound to the goal and the wanted status by
 * the page. Archiving returns to the dashboard (the goal has left it); everything else stays on
 * the goal.
 */
export async function changeGoalStatusAction(goalId: string, target: string): Promise<void> {
  if (!isGoalId(goalId) || !isGoalStatus(target)) notFound();
  const { accessToken } = await requireSession(goalPath(goalId));

  try {
    await setGoalStatus(accessToken, goalId, target);
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    if (error.isUnauthenticated) redirect(sessionEndedUrlFor(goalPath(goalId)));
    if (error.status === 404) notFound();
    redirect(`${goalPath(goalId)}?notice=${noticeForRefusal(error)}`);
  }

  redirect(
    target === "archived"
      ? `${DASHBOARD_PATH}?notice=archived`
      : `${goalPath(goalId)}?notice=${target}`,
  );
}

/** Permanently deletes an archived goal (the API and the database both refuse anything else). */
export async function deleteGoalAction(goalId: string): Promise<void> {
  if (!isGoalId(goalId)) notFound();
  const { accessToken } = await requireSession(goalPath(goalId));

  try {
    await deleteGoal(accessToken, goalId);
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    if (error.isUnauthenticated) redirect(sessionEndedUrlFor(goalPath(goalId)));
    if (error.status === 404) notFound();
    redirect(`${goalPath(goalId)}?notice=${noticeForRefusal(error)}`);
  }

  redirect(`${ARCHIVED_PATH}?notice=deleted`);
}

async function requireSession(returnTo: string): Promise<{ accessToken: string }> {
  const user = await getSessionUser();
  const accessToken = user ? await getAccessToken() : null;
  if (!accessToken) redirect(signInUrlFor(returnTo));
  return { accessToken };
}
