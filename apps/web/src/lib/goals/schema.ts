import { z } from "zod";

import {
  DEFAULT_DAILY_MINUTES,
  DEFAULT_LANGUAGES,
  DEFAULT_LEARNING_PREFERENCES,
  GOAL_LEVEL_OPTIONS,
  GOAL_TYPE_OPTIONS,
  LANGUAGE_OPTIONS,
  LEARNING_PREFERENCE_OPTIONS,
  MAX_DAILY_MINUTES,
  MIN_DAILY_MINUTES,
} from "@/lib/goals/options";
import { formString, formStrings, type FormState } from "@/lib/forms";
import type { Goal, GoalCreate, GoalUpdate, Preferences } from "@/lib/api/server";

const values = <T extends readonly { value: string }[]>(options: T) =>
  options.map((option) => option.value) as [T[number]["value"], ...T[number]["value"][]];

/** Shared by every form that asks for study time, languages or kinds of practice. */
export const dailyMinutesSchema = z.coerce
  .number({ error: "Enter a number of minutes." })
  .int("Use whole minutes.")
  .min(MIN_DAILY_MINUTES, `Plan for at least ${MIN_DAILY_MINUTES} minutes a day.`)
  .max(MAX_DAILY_MINUTES, `Plan for at most ${MAX_DAILY_MINUTES} minutes a day.`);

export const languagesSchema = z
  .array(z.enum(values(LANGUAGE_OPTIONS)))
  .min(1, "Choose at least one language.")
  .max(5);

export const learningPreferencesSchema = z
  .array(z.enum(values(LEARNING_PREFERENCE_OPTIONS)))
  .max(3);

/**
 * Validation for the goal forms. This is a user-experience layer that gives instant, field-level
 * messages; the API repeats and enforces every rule, and its errors are shown too.
 */
export const goalFormSchema = z.object({
  title: z
    .string()
    .trim()
    .min(1, "Describe what you want to learn.")
    .max(200, "Use 200 characters or fewer."),
  description: z.string().trim().max(2000, "Use 2000 characters or fewer."),
  goalType: z.enum(values(GOAL_TYPE_OPTIONS), { error: "Choose what kind of goal this is." }),
  currentLevel: z.enum(values(GOAL_LEVEL_OPTIONS), { error: "Choose your current level." }),
  targetDate: z
    .string()
    .trim()
    .refine((value) => value === "" || /^\d{4}-\d{2}-\d{2}$/.test(value), "Pick a valid date."),
  dailyMinutes: dailyMinutesSchema,
  languages: languagesSchema,
  learningPreferences: learningPreferencesSchema,
});

/** The first goal in onboarding: just the essentials. Time, languages and practice come from the
 *  preferences the learner saved a step earlier. */
export const quickGoalSchema = goalFormSchema.pick({
  title: true,
  description: true,
  goalType: true,
  currentLevel: true,
  targetDate: true,
});

export type GoalFormField =
  | "title"
  | "description"
  | "goalType"
  | "currentLevel"
  | "targetDate"
  | "dailyMinutes"
  | "languages"
  | "learningPreferences";

/** What the user typed, echoed back after a failed submit. */
export type GoalFormValues = {
  readonly title: string;
  readonly description: string;
  readonly goalType: string;
  readonly currentLevel: string;
  readonly targetDate: string;
  readonly dailyMinutes: string;
  readonly languages: readonly string[];
  readonly learningPreferences: readonly string[];
};

export type GoalFormState = FormState<GoalFormField, GoalFormValues>;

/** Read the goal form from a submission (strings only: nothing here is trusted yet). */
export function readGoalFormValues(formData: FormData): GoalFormValues {
  return {
    title: formString(formData, "title"),
    description: formString(formData, "description"),
    goalType: formString(formData, "goalType"),
    currentLevel: formString(formData, "currentLevel"),
    targetDate: formString(formData, "targetDate"),
    dailyMinutes: formString(formData, "dailyMinutes"),
    languages: formStrings(formData, "languages"),
    learningPreferences: formStrings(formData, "learningPreferences"),
  };
}

/** An empty new-goal form, starting from the learner's saved preferences (if any). */
export function newGoalDefaults(preferences?: Preferences): GoalFormValues {
  return {
    title: "",
    description: "",
    goalType: "professional_skill",
    currentLevel: "unknown",
    targetDate: "",
    dailyMinutes: String(preferences?.default_daily_minutes ?? DEFAULT_DAILY_MINUTES),
    languages: preferences?.preferred_languages ?? DEFAULT_LANGUAGES,
    learningPreferences: preferences?.learning_preferences ?? DEFAULT_LEARNING_PREFERENCES,
  };
}

/** A stored goal as form values, for the edit form. */
export function goalToFormValues(goal: Goal): GoalFormValues {
  return {
    title: goal.title,
    description: goal.description ?? "",
    goalType: goal.goal_type,
    currentLevel: goal.current_level,
    targetDate: goal.target_date ?? "",
    dailyMinutes: String(goal.daily_minutes),
    languages: goal.preferred_languages,
    learningPreferences: goal.learning_preferences,
  };
}

type ParsedGoalForm = z.output<typeof goalFormSchema>;

/** The request body for creating a goal. The owner is not part of it: the token names the owner. */
export function toCreateBody(goal: ParsedGoalForm): GoalCreate {
  return {
    title: goal.title,
    description: goal.description || null,
    goal_type: goal.goalType,
    current_level: goal.currentLevel,
    target_date: goal.targetDate || null,
    daily_minutes: goal.dailyMinutes,
    preferred_languages: goal.languages,
    learning_preferences: goal.learningPreferences,
  };
}

/** The request body for editing a goal. Blank optional fields are sent as null to clear them. */
export function toUpdateBody(goal: ParsedGoalForm): GoalUpdate {
  return toCreateBody(goal) satisfies GoalUpdate;
}

/** API field names (snake_case request body) -> form field names. */
const API_FIELD_TO_FORM_FIELD: Readonly<Record<string, GoalFormField>> = {
  title: "title",
  description: "description",
  goal_type: "goalType",
  current_level: "currentLevel",
  target_date: "targetDate",
  daily_minutes: "dailyMinutes",
  preferred_languages: "languages",
  learning_preferences: "learningPreferences",
};

export function mapApiFieldErrors(
  fieldErrors: Readonly<Record<string, string>>,
): Partial<Record<GoalFormField, string>> {
  const mapped: Partial<Record<GoalFormField, string>> = {};
  for (const [field, message] of Object.entries(fieldErrors)) {
    const formField = API_FIELD_TO_FORM_FIELD[field];
    if (formField) mapped[formField] = message;
  }
  return mapped;
}
