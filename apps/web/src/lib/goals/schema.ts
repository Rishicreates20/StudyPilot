import { z } from "zod";

import {
  GOAL_LEVEL_OPTIONS,
  GOAL_TYPE_OPTIONS,
  LANGUAGE_OPTIONS,
  MAX_DAILY_MINUTES,
  MIN_DAILY_MINUTES,
} from "@/lib/goals/options";
import type { FormState } from "@/lib/forms";

const values = <T extends readonly { value: string }[]>(options: T) =>
  options.map((option) => option.value) as [T[number]["value"], ...T[number]["value"][]];

/**
 * Validation for the create-goal form. This is a user-experience layer that gives instant,
 * field-level messages; the API repeats and enforces every rule, and its errors are shown too.
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
  dailyMinutes: z.coerce
    .number({ error: "Enter a number of minutes." })
    .int("Use whole minutes.")
    .min(MIN_DAILY_MINUTES, `Plan for at least ${MIN_DAILY_MINUTES} minutes a day.`)
    .max(MAX_DAILY_MINUTES, `Plan for at most ${MAX_DAILY_MINUTES} minutes a day.`),
  languages: z
    .array(z.enum(values(LANGUAGE_OPTIONS)))
    .min(1, "Choose at least one language.")
    .max(5),
});

export type GoalFormField =
  | "title"
  | "description"
  | "goalType"
  | "currentLevel"
  | "targetDate"
  | "dailyMinutes"
  | "languages";

/** What the user typed, echoed back after a failed submit. */
export type GoalFormValues = {
  readonly title: string;
  readonly description: string;
  readonly goalType: string;
  readonly currentLevel: string;
  readonly targetDate: string;
  readonly dailyMinutes: string;
  readonly languages: readonly string[];
};

export type GoalFormState = FormState<GoalFormField, GoalFormValues>;

/** API field names (snake_case request body) -> form field names. */
const API_FIELD_TO_FORM_FIELD: Readonly<Record<string, GoalFormField>> = {
  title: "title",
  description: "description",
  goal_type: "goalType",
  current_level: "currentLevel",
  target_date: "targetDate",
  daily_minutes: "dailyMinutes",
  preferred_languages: "languages",
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
