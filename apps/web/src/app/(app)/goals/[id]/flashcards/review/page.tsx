import { ArrowLeftIcon, CheckCircle2Icon, InfoIcon } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { connection } from "next/server";
import { Suspense } from "react";

import { ReviewCard } from "@/components/flashcards/review-card";
import { NoticeBanner } from "@/components/feedback/notice-banner";
import { PageContainer, PageHeader } from "@/components/layout/page";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { callApi } from "@/lib/api/call";
import { fetchDueFlashcards, fetchGoal } from "@/lib/api/server";
import { whenDue } from "@/lib/flashcards/labels";
import { flashcardsPath, reviewPath } from "@/lib/flashcards/paths";
import { goalPath, isGoalId } from "@/lib/goals/ids";
import { firstParam, type SearchParams } from "@/lib/search-params";

export const metadata: Metadata = { title: "Review flashcards" };

type ReviewPageProps = {
  params: Promise<{ id: string }>;
  searchParams: SearchParams;
};

export default function ReviewPage(props: ReviewPageProps) {
  return (
    <PageContainer className="max-w-2xl py-8">
      <Suspense
        fallback={
          <div className="space-y-6" role="status" aria-label="Loading your review">
            <Skeleton className="h-10 w-1/2" />
            <Skeleton className="h-64 w-full" />
          </div>
        }
      >
        <ReviewContent {...props} />
      </Suspense>
    </PageContainer>
  );
}

async function ReviewContent({ params, searchParams }: ReviewPageProps) {
  await connection();
  const { id } = await params;
  if (!isGoalId(id)) notFound();
  const query = await searchParams;

  const { goal, queue } = await callApi(reviewPath(id), async (accessToken) => {
    const [goal, queue] = await Promise.all([
      fetchGoal(accessToken, id),
      fetchDueFlashcards(accessToken, id, 1),
    ]);
    return { goal, queue };
  });

  const archived = goal.status === "archived";
  const card = queue.cards[0];
  const { summary } = queue;

  return (
    <div className="space-y-8">
      <Link
        href={flashcardsPath(id)}
        className="inline-flex items-center gap-1.5 rounded-sm text-sm text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
      >
        <ArrowLeftIcon className="size-4" aria-hidden="true" />
        Back to all cards
      </Link>

      <PageHeader
        title="Review"
        description={
          card && !archived
            ? `${summary.due_now} due now. Try to remember the answer before you open it.`
            : undefined
        }
      />

      <NoticeBanner code={firstParam(query.notice)} />

      {archived ? (
        <Alert variant="info">
          <InfoIcon aria-hidden="true" />
          <AlertDescription>
            This goal is archived, so its cards can&rsquo;t be reviewed. Restore the goal to carry
            on.
          </AlertDescription>
        </Alert>
      ) : card ? (
        <ReviewCard
          // A new key for each showing of a card: pressing a rating twice is one review.
          key={card.id}
          goalId={id}
          cardId={card.id}
          front={card.front}
          back={card.back}
          reviewKey={crypto.randomUUID()}
        />
      ) : (
        <div className="space-y-4 rounded-2xl border bg-card p-8 text-center">
          <CheckCircle2Icon
            className="mx-auto size-10 text-success-foreground"
            aria-hidden="true"
          />
          <h2 className="font-heading text-xl font-semibold tracking-tight">
            {summary.total === 0 ? "No cards yet" : "You're all caught up"}
          </h2>
          <p className="text-sm text-muted-foreground">
            {summary.total === 0
              ? "Add a card and it will be ready to review straight away."
              : summary.reviewed_today > 0
                ? `You reviewed ${summary.reviewed_today} today. `
                : ""}
            {summary.next_due_at
              ? `The next card is due: ${whenDue({ is_due: false, due_at: summary.next_due_at }, new Date()).replace(/^Due /, "")}.`
              : ""}
          </p>
          <div className="flex flex-wrap justify-center gap-2">
            <Button asChild variant="outline">
              <Link href={flashcardsPath(id)}>Manage cards</Link>
            </Button>
            <Button asChild variant="ghost">
              <Link href={goalPath(id)}>Back to the goal</Link>
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
