import { ArrowLeftIcon, InfoIcon, LayersIcon } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { connection } from "next/server";
import { Suspense } from "react";

import { AddCardForm } from "@/components/flashcards/add-card-form";
import { CardRow } from "@/components/flashcards/card-row";
import { EmptyState } from "@/components/feedback/empty-state";
import { NoticeBanner } from "@/components/feedback/notice-banner";
import { PageContainer, PageHeader } from "@/components/layout/page";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { callApi } from "@/lib/api/call";
import { fetchFlashcards, fetchGoal } from "@/lib/api/server";
import { cardStage, deckSentence, whenDue } from "@/lib/flashcards/labels";
import { flashcardsPath, reviewPath } from "@/lib/flashcards/paths";
import { goalPath, isGoalId } from "@/lib/goals/ids";
import { firstParam, type SearchParams } from "@/lib/search-params";

export const metadata: Metadata = { title: "Flashcards" };

type FlashcardsPageProps = {
  params: Promise<{ id: string }>;
  searchParams: SearchParams;
};

export default function FlashcardsPage(props: FlashcardsPageProps) {
  return (
    <PageContainer className="max-w-3xl py-8">
      <Suspense
        fallback={
          <div className="space-y-6" role="status" aria-label="Loading the flashcards">
            <Skeleton className="h-10 w-2/3" />
            <Skeleton className="h-40 w-full" />
            <Skeleton className="h-24 w-full" />
          </div>
        }
      >
        <FlashcardsContent {...props} />
      </Suspense>
    </PageContainer>
  );
}

async function FlashcardsContent({ params, searchParams }: FlashcardsPageProps) {
  await connection();
  const { id } = await params;
  if (!isGoalId(id)) notFound();
  const query = await searchParams;

  // A missing goal and someone else's goal are the same 404.
  const { goal, deck } = await callApi(flashcardsPath(id), async (accessToken) => {
    const [goal, deck] = await Promise.all([
      fetchGoal(accessToken, id),
      fetchFlashcards(accessToken, id),
    ]);
    return { goal, deck };
  });

  const archived = goal.status === "archived";
  const { summary } = deck;
  const now = new Date();

  return (
    <div className="space-y-8">
      <Link
        href={goalPath(id)}
        className="inline-flex items-center gap-1.5 rounded-sm text-sm text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
      >
        <ArrowLeftIcon className="size-4" aria-hidden="true" />
        Back to {goal.title}
      </Link>

      <PageHeader
        title="Flashcards"
        description={`${deckSentence(summary)} Cards come back on a schedule that suggests when you are about to forget them. It is a rule of thumb, not a measure of what you know.`}
        actions={
          summary.due_now > 0 && !archived ? (
            <Button asChild>
              <Link href={reviewPath(id)}>Review {summary.due_now} due</Link>
            </Button>
          ) : null
        }
      />

      <NoticeBanner code={firstParam(query.notice)} />

      {archived ? (
        <Alert variant="info">
          <InfoIcon aria-hidden="true" />
          <AlertDescription>
            This goal is archived, so its cards are read-only. Restore the goal to add, edit or
            review them.
          </AlertDescription>
        </Alert>
      ) : (
        <AddCardForm goalId={id} />
      )}

      <section aria-labelledby="deck-heading" className="space-y-4">
        <h2 id="deck-heading" className="font-heading text-xl font-semibold tracking-tight">
          Your cards
        </h2>
        {deck.cards.length === 0 ? (
          <EmptyState
            icon={LayersIcon}
            title="No cards yet"
            description={
              archived
                ? "This goal has no flashcards."
                : "Add your first card above. Short, single-fact cards work best."
            }
            headingLevel="h3"
          />
        ) : (
          <ul className="space-y-3">
            {deck.cards.map((card) => (
              <CardRow
                key={card.id}
                goalId={id}
                cardId={card.id}
                front={card.front}
                back={card.back}
                dueLabel={whenDue(card, now)}
                stage={cardStage(card)}
                readOnly={archived}
              />
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
