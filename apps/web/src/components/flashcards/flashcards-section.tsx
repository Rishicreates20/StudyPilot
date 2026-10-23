import { LayersIcon } from "lucide-react";
import Link from "next/link";
import { redirect } from "next/navigation";
import { connection } from "next/server";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, fetchFlashcards, type GoalStatus } from "@/lib/api/server";
import { sessionEndedUrlFor } from "@/lib/auth/paths";
import { requireApiSession } from "@/lib/auth/session";
import { flashcardsPath, reviewPath } from "@/lib/flashcards/paths";
import { deckSentence } from "@/lib/flashcards/labels";
import { goalPath } from "@/lib/goals/ids";

export function FlashcardsSectionSkeleton() {
  return (
    <div className="space-y-4" role="status" aria-label="Loading the flashcards">
      <Skeleton className="h-7 w-40" />
      <Skeleton className="h-20 w-full" />
    </div>
  );
}

/**
 * The goal page's flashcards summary: how many cards there are, how many are due, and a way in.
 * Loaded on its own so the goal appears first; if it can't be loaded it says so in a line instead
 * of taking the page down (the roadmap and the rest do not depend on it).
 */
export async function FlashcardsSection({
  goalId,
  goalStatus,
}: {
  goalId: string;
  goalStatus: GoalStatus;
}) {
  await connection();
  const { accessToken } = await requireApiSession(goalPath(goalId));
  let deck;
  try {
    deck = await fetchFlashcards(accessToken, goalId);
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    if (error.isUnauthenticated) redirect(sessionEndedUrlFor(goalPath(goalId)));
    return (
      <section aria-labelledby="cards-heading" className="space-y-2">
        <h2 id="cards-heading" className="font-heading text-xl font-semibold tracking-tight">
          Flashcards
        </h2>
        <p className="text-sm text-muted-foreground">
          Your flashcards couldn&rsquo;t be loaded just now.{" "}
          <Link href={flashcardsPath(goalId)} className="underline underline-offset-4">
            Open flashcards
          </Link>
        </p>
      </section>
    );
  }

  const { summary } = deck;
  const archived = goalStatus === "archived";

  return (
    <section aria-labelledby="cards-heading" className="space-y-3">
      <h2 id="cards-heading" className="font-heading text-xl font-semibold tracking-tight">
        Flashcards
      </h2>
      <div className="flex flex-col gap-4 rounded-xl border bg-card p-5 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-start gap-3">
          <LayersIcon className="mt-0.5 size-5 shrink-0 text-primary" aria-hidden="true" />
          <p className="text-sm leading-6">
            {summary.total === 0
              ? "Make cards for the things you need to remember, and they will come back just before you would forget them."
              : deckSentence(summary)}
            {summary.reviewed_today > 0
              ? ` You have reviewed ${summary.reviewed_today} today.`
              : ""}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {summary.due_now > 0 && !archived ? (
            <Button asChild>
              <Link href={reviewPath(goalId)}>Review {summary.due_now} due</Link>
            </Button>
          ) : null}
          <Button asChild variant="outline">
            <Link href={flashcardsPath(goalId)}>
              {summary.total === 0 && !archived ? "Add your first card" : "Manage cards"}
            </Link>
          </Button>
        </div>
      </div>
    </section>
  );
}
