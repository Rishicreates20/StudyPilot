"use server";

import { redirect } from "next/navigation";

import { ApiError, createGoal } from "@/lib/api/server";
import { DASHBOARD_PATH, sessionEndedUrlFor, signInUrlFor } from "@/lib/auth/paths";
import { getAccessToken, getSessionUser } from "@/lib/auth/session";
import { formString, zodFieldErrors } from "@/lib/forms";
import {
  goalFormSchema,
  mapApiFieldErrors,
  type GoalFormState,
  type GoalFormValues,
} from "@/lib/goals/schema";

const NEW_GOAL_PATH = "/goals/new";

function failureMessage(error: ApiError): string {
  if (error.code === "GOAL_LIMIT_REACHED") return error.message; // already user-safe wording
  if (error.status === 0 || error.status === 503) {
    return "We can't reach the learning service right now. Your goal was not saved. Please try again in a moment.";
  }
  if (error.status === 422) return "Some details need fixing. Check the highlighted fields.";
  const reference = error.requestId ? ` (reference: ${error.requestId})` : "";
  return `We couldn't save your goal${reference}. Please try again.`;
}

/**
 * Creates a goal for the signed-in user.
 *
 * The owner is never part of the request: the API derives it from the access token it verifies.
 * Session checks here only decide where to send the visitor; they are not the security boundary.
 */
export async function createGoalAction(
  _previous: GoalFormState,
  formData: FormData,
): Promise<GoalFormState> {
  const values: GoalFormValues = {
    title: formString(formData, "title"),
    description: formString(formData, "description"),
    goalType: formString(formData, "goalType"),
    currentLevel: formString(formData, "currentLevel"),
    targetDate: formString(formData, "targetDate"),
    dailyMinutes: formString(formData, "dailyMinutes"),
    languages: formData.getAll("languages").filter((v): v is string => typeof v === "string"),
  };

  const parsed = goalFormSchema.safeParse(values);
  if (!parsed.success) {
    return { status: "error", fieldErrors: zodFieldErrors(parsed.error), values };
  }

  const user = await getSessionUser();
  const accessToken = user ? await getAccessToken() : null;
  if (!accessToken) redirect(signInUrlFor(NEW_GOAL_PATH));

  const goal = parsed.data;
  try {
    await createGoal(accessToken, {
      title: goal.title,
      description: goal.description || null,
      goal_type: goal.goalType,
      current_level: goal.currentLevel,
      target_date: goal.targetDate || null,
      daily_minutes: goal.dailyMinutes,
      preferred_languages: goal.languages,
    });
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    // The API rejected the token (expired, revoked, account deleted): sign in again.
    if (error.isUnauthenticated) redirect(sessionEndedUrlFor(NEW_GOAL_PATH));
    return {
      status: "error",
      formError: failureMessage(error),
      fieldErrors: mapApiFieldErrors(error.fieldErrors),
      values,
    };
  }

  redirect(`${DASHBOARD_PATH}?created=1`);
}
