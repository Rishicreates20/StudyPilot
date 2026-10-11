"use server";

import { redirect } from "next/navigation";

import { failureMessage } from "@/lib/api/failure";
import { ApiError, completeOnboarding, createGoal, updateMe } from "@/lib/api/server";
import { DASHBOARD_PATH, sessionEndedUrlFor, signInUrlFor } from "@/lib/auth/paths";
import { getAccessToken, getSessionUser } from "@/lib/auth/session";
import { zodFieldErrors } from "@/lib/forms";
import {
  mapApiFieldErrors,
  quickGoalSchema,
  readGoalFormValues,
  type GoalFormField,
  type GoalFormState,
} from "@/lib/goals/schema";
import { ONBOARDING_PATH, onboardingStepPath } from "@/lib/onboarding/paths";
import {
  aboutYouSchema,
  mapApiSettingsErrors,
  readSettingsValues,
  studyStyleSchema,
  type SettingsState,
} from "@/lib/profile/schema";

/**
 * The onboarding steps. Each one saves on its own (so a refresh, or coming back tomorrow, loses
 * nothing) and then moves to the next. The first goal is created last, with the study time,
 * languages and kinds of practice the learner just saved; finishing or skipping marks onboarding
 * as done on the server, which is what the dashboard checks.
 */

async function requireToken(returnTo: string): Promise<string> {
  const user = await getSessionUser();
  const accessToken = user ? await getAccessToken() : null;
  if (!accessToken) redirect(signInUrlFor(returnTo));
  return accessToken;
}

/** Step 1: name (optional) and languages. */
export async function saveAboutYouAction(
  _previous: SettingsState,
  formData: FormData,
): Promise<SettingsState> {
  const values = readSettingsValues(formData);
  const parsed = aboutYouSchema.safeParse(values);
  if (!parsed.success) {
    return { status: "error", fieldErrors: zodFieldErrors(parsed.error), values };
  }
  const accessToken = await requireToken(onboardingStepPath(1));

  try {
    await updateMe(accessToken, {
      display_name: parsed.data.displayName || null,
      preferred_languages: parsed.data.languages,
    });
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    if (error.isUnauthenticated) redirect(sessionEndedUrlFor(onboardingStepPath(1)));
    return {
      status: "error",
      formError: failureMessage(error, "answers"),
      fieldErrors: mapApiSettingsErrors(error.fieldErrors),
      values,
    };
  }
  redirect(onboardingStepPath(2));
}

/** Step 2: daily study time and kinds of practice. */
export async function saveStudyStyleAction(
  _previous: SettingsState,
  formData: FormData,
): Promise<SettingsState> {
  const values = readSettingsValues(formData);
  const parsed = studyStyleSchema.safeParse(values);
  if (!parsed.success) {
    return { status: "error", fieldErrors: zodFieldErrors(parsed.error), values };
  }
  const accessToken = await requireToken(onboardingStepPath(2));

  try {
    await updateMe(accessToken, {
      default_daily_minutes: parsed.data.dailyMinutes,
      learning_preferences: parsed.data.learningPreferences,
    });
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    if (error.isUnauthenticated) redirect(sessionEndedUrlFor(onboardingStepPath(2)));
    return {
      status: "error",
      formError: failureMessage(error, "answers"),
      fieldErrors: mapApiSettingsErrors(error.fieldErrors),
      values,
    };
  }
  redirect(onboardingStepPath(3));
}

/** Step 3: the first goal (only the essentials), then onboarding is complete. */
export async function createFirstGoalAction(
  _previous: GoalFormState,
  formData: FormData,
): Promise<GoalFormState> {
  const values = readGoalFormValues(formData);
  const parsed = quickGoalSchema.safeParse(values);
  if (!parsed.success) {
    return { status: "error", fieldErrors: zodFieldErrors<GoalFormField>(parsed.error), values };
  }
  const accessToken = await requireToken(onboardingStepPath(3));

  const goal = parsed.data;
  try {
    // Study time, languages and kinds of practice are left out on purpose: the API fills them in
    // from the preferences saved in steps 1 and 2.
    await createGoal(accessToken, {
      title: goal.title,
      description: goal.description || null,
      goal_type: goal.goalType,
      current_level: goal.currentLevel,
      target_date: goal.targetDate || null,
    });
    await completeOnboarding(accessToken);
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    if (error.isUnauthenticated) redirect(sessionEndedUrlFor(onboardingStepPath(3)));
    return {
      status: "error",
      formError: failureMessage(error, "goal"),
      fieldErrors: mapApiFieldErrors(error.fieldErrors),
      values,
    };
  }
  redirect(`${DASHBOARD_PATH}?notice=onboarded`);
}

/** "Skip for now": onboarding is marked done without a goal. */
export async function skipOnboardingAction(): Promise<void> {
  const accessToken = await requireToken(ONBOARDING_PATH);
  try {
    await completeOnboarding(accessToken);
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    if (error.isUnauthenticated) redirect(sessionEndedUrlFor(ONBOARDING_PATH));
    redirect(`${ONBOARDING_PATH}?notice=unavailable`);
  }
  redirect(`${DASHBOARD_PATH}?notice=skipped`);
}
