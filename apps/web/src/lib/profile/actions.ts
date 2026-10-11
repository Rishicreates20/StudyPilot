"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { failureMessage } from "@/lib/api/failure";
import { ApiError, updateMe } from "@/lib/api/server";
import { sessionEndedUrlFor, signInUrlFor } from "@/lib/auth/paths";
import { getAccessToken, getSessionUser } from "@/lib/auth/session";
import { zodFieldErrors } from "@/lib/forms";
import {
  mapApiSettingsErrors,
  readSettingsValues,
  settingsSchema,
  type SettingsState,
} from "@/lib/profile/schema";

const SETTINGS_PATH = "/settings";

/** Saves the settings page. The profile saved is always the token holder's. */
export async function saveSettingsAction(
  _previous: SettingsState,
  formData: FormData,
): Promise<SettingsState> {
  const values = readSettingsValues(formData);
  const parsed = settingsSchema.safeParse(values);
  if (!parsed.success) {
    return { status: "error", fieldErrors: zodFieldErrors(parsed.error), values };
  }

  const user = await getSessionUser();
  const accessToken = user ? await getAccessToken() : null;
  if (!accessToken) redirect(signInUrlFor(SETTINGS_PATH));

  const settings = parsed.data;
  try {
    await updateMe(accessToken, {
      display_name: settings.displayName || null,
      timezone: settings.timezone,
      default_daily_minutes: settings.dailyMinutes,
      preferred_languages: settings.languages,
      learning_preferences: settings.learningPreferences,
    });
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    if (error.isUnauthenticated) redirect(sessionEndedUrlFor(SETTINGS_PATH));
    return {
      status: "error",
      formError: failureMessage(error, "preferences"),
      fieldErrors: mapApiSettingsErrors(error.fieldErrors),
      values,
    };
  }

  // Other pages (the new-goal form, onboarding) read these settings: make them fetch afresh.
  revalidatePath(SETTINGS_PATH);
  return {
    status: "success",
    message: "Your preferences are saved.",
    values: {
      displayName: settings.displayName,
      timezone: settings.timezone,
      dailyMinutes: String(settings.dailyMinutes),
      languages: settings.languages,
      learningPreferences: settings.learningPreferences,
    },
  };
}
