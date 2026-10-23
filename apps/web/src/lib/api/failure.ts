import type { ApiError } from "@/lib/api/server";

/** API codes whose message was written for the learner and can be shown as it is. */
const USER_SAFE_CODES: ReadonlySet<string> = new Set([
  "GOAL_LIMIT_REACHED",
  "GOAL_ARCHIVED",
  "GOAL_NOT_ARCHIVED",
  "INVALID_STATUS_TRANSITION",
  // Documents: the API wrote these sentences for the learner (they never contain file content).
  "DOCUMENT_EXISTS",
  "DOCUMENT_LIMIT_REACHED",
  "DOCUMENT_LIMIT_REACHED_TODAY",
  "FILE_TOO_LARGE",
  "FILE_TYPE_UNSUPPORTED",
  "FILE_TYPE_MISMATCH",
  "FILE_EMPTY",
  "STORAGE_NOT_CONFIGURED",
  "AI_NOT_CONFIGURED",
  // Flashcards: written for the learner, they never contain what a card says.
  "FLASHCARD_LIMIT_REACHED",
  "UNKNOWN_TOPIC",
]);

/**
 * What to tell the learner when saving something failed. `subject` is the thing being saved
 * ("goal", "preferences"). When the service is down the message says plainly that nothing was
 * saved, because that is what a person wants to know first.
 */
export function failureMessage(error: ApiError, subject: string): string {
  if (USER_SAFE_CODES.has(error.code)) return error.message;
  if (error.status === 0 || error.status === 503) {
    return `We can't reach the learning service right now, so nothing was saved. Please try again in a moment.`;
  }
  if (error.status === 422) return "Some details need fixing. Check the highlighted fields.";
  const reference = error.requestId ? ` (reference: ${error.requestId})` : "";
  return `We couldn't save your ${subject}${reference}. Please try again.`;
}
