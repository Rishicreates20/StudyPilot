import { goalPath } from "@/lib/goals/ids";

/** A goal's flashcards: the deck, a form to add a card, and a way into a review. */
export const flashcardsPath = (goalId: string) => `${goalPath(goalId)}/flashcards`;

/** A review session: the cards that are due now, one at a time. */
export const reviewPath = (goalId: string) => `${flashcardsPath(goalId)}/review`;
