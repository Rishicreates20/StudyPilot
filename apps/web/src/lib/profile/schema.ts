import { z } from "zod";

import { formString, formStrings, type FormState } from "@/lib/forms";
import { dailyMinutesSchema, languagesSchema, learningPreferencesSchema } from "@/lib/goals/schema";
import type { Me } from "@/lib/api/server";

const displayName = z.string().trim().max(80, "Use 80 characters or fewer.");

/** The settings page: everything the learner can save about themselves. */
export const settingsSchema = z.object({
  displayName,
  timezone: z.string().trim().min(1, "Choose a timezone.").max(64, "Choose a timezone."),
  dailyMinutes: dailyMinutesSchema,
  languages: languagesSchema,
  learningPreferences: learningPreferencesSchema,
});

/** Onboarding step 1: who you are and which languages you study in. */
export const aboutYouSchema = settingsSchema.pick({ displayName: true, languages: true });

/** Onboarding step 2: how much time you have and how you like to study. */
export const studyStyleSchema = settingsSchema.pick({
  dailyMinutes: true,
  learningPreferences: true,
});

export type SettingsField =
  "displayName" | "timezone" | "dailyMinutes" | "languages" | "learningPreferences";

export type SettingsValues = {
  readonly displayName: string;
  readonly timezone: string;
  readonly dailyMinutes: string;
  readonly languages: readonly string[];
  readonly learningPreferences: readonly string[];
};

export type SettingsState = FormState<SettingsField, SettingsValues>;

export function readSettingsValues(formData: FormData): SettingsValues {
  return {
    displayName: formString(formData, "displayName"),
    timezone: formString(formData, "timezone"),
    dailyMinutes: formString(formData, "dailyMinutes"),
    languages: formStrings(formData, "languages"),
    learningPreferences: formStrings(formData, "learningPreferences"),
  };
}

/** The saved profile as form values. */
export function meToSettingsValues(me: Me): SettingsValues {
  return {
    displayName: me.display_name ?? "",
    timezone: me.timezone,
    dailyMinutes: String(me.preferences.default_daily_minutes),
    languages: me.preferences.preferred_languages,
    learningPreferences: me.preferences.learning_preferences,
  };
}

/** API field names -> form field names (for errors the API reports). */
const API_FIELD_TO_SETTINGS_FIELD: Readonly<Record<string, SettingsField>> = {
  display_name: "displayName",
  timezone: "timezone",
  default_daily_minutes: "dailyMinutes",
  preferred_languages: "languages",
  learning_preferences: "learningPreferences",
};

export function mapApiSettingsErrors(
  fieldErrors: Readonly<Record<string, string>>,
): Partial<Record<SettingsField, string>> {
  const mapped: Partial<Record<SettingsField, string>> = {};
  for (const [field, message] of Object.entries(fieldErrors)) {
    const formField = API_FIELD_TO_SETTINGS_FIELD[field];
    if (formField) mapped[formField] = message;
  }
  return mapped;
}
