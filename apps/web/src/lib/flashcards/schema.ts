import { z } from "zod";

import type { FlashcardRating } from "@/lib/api/server";
import type { FormState } from "@/lib/forms";

/** Limits that mirror the API's (it checks them again; these only give fast, friendly feedback). */
export const MAX_FRONT_CHARS = 1000;
export const MAX_BACK_CHARS = 2000;

export const cardFormSchema = z.object({
  front: z
    .string()
    .trim()
    .min(1, "Write the question or prompt.")
    .max(MAX_FRONT_CHARS, `Use ${MAX_FRONT_CHARS} characters or fewer.`),
  back: z
    .string()
    .trim()
    .min(1, "Write the answer.")
    .max(MAX_BACK_CHARS, `Use ${MAX_BACK_CHARS} characters or fewer.`),
});

export type CardFormState = FormState<"front" | "back">;

/** The four ratings, hardest first. The server decides what each one does to the schedule. */
export const RATINGS: readonly FlashcardRating[] = ["again", "hard", "good", "easy"];

export function isRating(value: unknown): value is FlashcardRating {
  return typeof value === "string" && (RATINGS as readonly string[]).includes(value);
}

/** A review's idempotency key: made by the page (a fresh UUID per card shown), checked here. */
const KEY = /^[A-Za-z0-9-]{8,128}$/;

export function isReviewKey(value: unknown): value is string {
  return typeof value === "string" && KEY.test(value);
}
