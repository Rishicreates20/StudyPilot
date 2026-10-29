"use server";

import { revalidatePath } from "next/cache";
import { notFound, redirect } from "next/navigation";

import { failureMessage } from "@/lib/api/failure";
import {
  ApiError,
  createFlashcard,
  deleteFlashcard,
  reviewFlashcard,
  updateFlashcard,
} from "@/lib/api/server";
import { requireSession } from "@/lib/auth/action-session";
import { sessionEndedUrlFor } from "@/lib/auth/paths";
import { flashcardsPath, reviewPath } from "@/lib/flashcards/paths";
import { cardFormSchema, isRating, isReviewKey, type CardFormState } from "@/lib/flashcards/schema";
import { formString, zodFieldErrors } from "@/lib/forms";
import { isGoalId } from "@/lib/goals/ids";

/**
 * Adding, editing and deleting a card, and rating a card in a review.
 *
 * The same rules as everywhere else: nothing here names an owner (the API derives it from the
 * verified token and answers 404 for anything that is not the caller's), identifiers from the
 * browser are checked before they reach an API path, and the schedule is never sent: the browser
 * says only how well a card was remembered, and the server decides when it comes back.
 */

function checkIds(...ids: string[]): void {
  if (!ids.every(isGoalId)) notFound();
}

function withNotice(path: string, notice: string): string {
  return `${path}?notice=${notice}`;
}

/** Add a card to a goal. Bound to the goal by the page. */
export async function createFlashcardAction(
  goalId: string,
  _previous: CardFormState,
  formData: FormData,
): Promise<CardFormState> {
  checkIds(goalId);
  const values = { front: formString(formData, "front"), back: formString(formData, "back") };
  const parsed = cardFormSchema.safeParse(values);
  if (!parsed.success) {
    return { status: "error", fieldErrors: zodFieldErrors(parsed.error), values };
  }

  const page = flashcardsPath(goalId);
  const { accessToken } = await requireSession(page);
  try {
    await createFlashcard(accessToken, goalId, parsed.data);
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    if (error.isUnauthenticated) redirect(sessionEndedUrlFor(page));
    if (error.status === 404) notFound();
    return { status: "error", formError: failureMessage(error, "card"), fieldErrors: {}, values };
  }

  revalidatePath(page);
  return { status: "success", message: "Card added.", values: { front: "", back: "" } };
}

/** Change a card's two sides. Bound to the goal and the card. */
export async function updateFlashcardAction(
  goalId: string,
  cardId: string,
  _previous: CardFormState,
  formData: FormData,
): Promise<CardFormState> {
  checkIds(goalId, cardId);
  const values = { front: formString(formData, "front"), back: formString(formData, "back") };
  const parsed = cardFormSchema.safeParse(values);
  if (!parsed.success) {
    return { status: "error", fieldErrors: zodFieldErrors(parsed.error), values };
  }

  const page = flashcardsPath(goalId);
  const { accessToken } = await requireSession(page);
  try {
    await updateFlashcard(accessToken, cardId, parsed.data);
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    if (error.isUnauthenticated) redirect(sessionEndedUrlFor(page));
    if (error.status === 404) notFound();
    return { status: "error", formError: failureMessage(error, "card"), fieldErrors: {}, values };
  }

  revalidatePath(page);
  return { status: "success", message: "Card saved.", values: parsed.data };
}

/** Delete a card and its review history. Bound to the goal and the card. */
export async function deleteFlashcardAction(goalId: string, cardId: string): Promise<void> {
  checkIds(goalId, cardId);
  const page = flashcardsPath(goalId);
  const { accessToken } = await requireSession(page);
  try {
    await deleteFlashcard(accessToken, cardId);
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    if (error.isUnauthenticated) redirect(sessionEndedUrlFor(page));
    if (error.status === 404) notFound();
    redirect(withNotice(page, error.status === 409 ? "goal-archived" : "card-failed"));
  }
  redirect(withNotice(page, "card-deleted"));
}

/**
 * Rate the card on screen. Bound to the goal and the card; the form carries the rating (the
 * button pressed) and a key the page made for this showing of the card, so a double click counts
 * once. Whatever happens, the learner ends on the review page, which shows the real next card.
 */
export async function reviewFlashcardAction(
  goalId: string,
  cardId: string,
  formData: FormData,
): Promise<void> {
  checkIds(goalId, cardId);
  const page = reviewPath(goalId);
  const rating = formString(formData, "rating");
  const key = formString(formData, "key");
  if (!isRating(rating) || !isReviewKey(key)) redirect(withNotice(page, "review-failed"));

  const { accessToken } = await requireSession(page);
  try {
    await reviewFlashcard(accessToken, cardId, rating, key);
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    if (error.isUnauthenticated) redirect(sessionEndedUrlFor(page));
    if (error.status === 404) notFound();
    redirect(withNotice(page, error.status === 409 ? "goal-archived" : "review-failed"));
  }
  redirect(page);
}
