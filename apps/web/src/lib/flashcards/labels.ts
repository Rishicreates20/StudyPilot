import type { Flashcard, FlashcardRating } from "@/lib/api/server";

/** The rating buttons: what they are called and what each one means in plain words. */
export const RATING_OPTIONS: readonly {
  value: FlashcardRating;
  label: string;
  hint: string;
}[] = [
  { value: "again", label: "Again", hint: "I forgot it" },
  { value: "hard", label: "Hard", hint: "I barely remembered" },
  { value: "good", label: "Good", hint: "I remembered it" },
  { value: "easy", label: "Easy", hint: "It was too easy" },
];

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

function plural(count: number, unit: string): string {
  return `${count} ${unit}${count === 1 ? "" : "s"}`;
}

/**
 * When a card will next be shown, in words: "Due now", "Due in 10 minutes", "Due tomorrow".
 * Whether it is due comes from the server's clock (`is_due`); `now` only words the wait, so a
 * browser with a wrong clock cannot make a card look due when it is not.
 */
export function whenDue(card: Pick<Flashcard, "is_due" | "due_at">, now: Date): string {
  if (card.is_due) return "Due now";
  const wait = new Date(card.due_at).getTime() - now.getTime();
  if (wait < HOUR) return `Due in ${plural(Math.max(1, Math.ceil(wait / MINUTE)), "minute")}`;
  if (wait < DAY) return `Due in ${plural(Math.ceil(wait / HOUR), "hour")}`;
  const days = Math.round(wait / DAY);
  return days <= 1 ? "Due tomorrow" : `Due in ${days} days`;
}

/** How a card is doing, for a quiet label next to it (never a score). */
export function cardStage(
  card: Pick<Flashcard, "repetitions" | "lapses" | "last_reviewed_at">,
): string {
  if (card.last_reviewed_at === null) return "New";
  if (card.repetitions === 0) return "Relearning";
  return card.repetitions < 3 ? "Learning" : "Review";
}

/** The deck summary as one sentence. */
export function deckSentence(summary: { total: number; due_now: number }): string {
  if (summary.total === 0) return "No cards yet.";
  const total = plural(summary.total, "card");
  if (summary.due_now === 0) return `${total}. Nothing is due right now.`;
  return `${total}. ${summary.due_now} due now.`;
}
