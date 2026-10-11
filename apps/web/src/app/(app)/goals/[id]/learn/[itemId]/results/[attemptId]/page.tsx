import { ArrowLeftIcon, InfoIcon } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { connection } from "next/server";
import { Suspense } from "react";

import { NoticeBanner } from "@/components/feedback/notice-banner";
import { PageContainer, PageHeader } from "@/components/layout/page";
import { ResultsView } from "@/components/quiz/results-view";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { callApi } from "@/lib/api/call";
import { fetchAttempt, fetchGoal, fetchMe } from "@/lib/api/server";
import { isGoalId } from "@/lib/goals/ids";
import { studyPath } from "@/lib/lessons/paths";
import { resultsPath } from "@/lib/quizzes/paths";
import { firstParam, type SearchParams } from "@/lib/search-params";

export const metadata: Metadata = { title: "Quiz results" };

type ResultsPageProps = {
  params: Promise<{ id: string; itemId: string; attemptId: string }>;
  searchParams: SearchParams;
};

export default function ResultsPage(props: ResultsPageProps) {
  return (
    <PageContainer className="max-w-3xl py-8">
      <Suspense
        fallback={
          <div className="space-y-6" role="status" aria-label="Loading your results">
            <Skeleton className="h-10 w-2/3" />
            <Skeleton className="h-40 w-full" />
            <Skeleton className="h-64 w-full" />
          </div>
        }
      >
        <ResultsContent {...props} />
      </Suspense>
    </PageContainer>
  );
}

async function ResultsContent({ params, searchParams }: ResultsPageProps) {
  await connection(); // marking finishes under us: never reuse a rendered answer
  const { id, itemId, attemptId } = await params;
  if (!isGoalId(id) || !isGoalId(itemId) || !isGoalId(attemptId)) notFound();
  const query = await searchParams;

  // A missing attempt and someone else's attempt are the same 404.
  const { result, goal, me } = await callApi(
    resultsPath(id, itemId, attemptId),
    async (accessToken) => {
      const [result, goal, me] = await Promise.all([
        fetchAttempt(accessToken, attemptId),
        fetchGoal(accessToken, id),
        fetchMe(accessToken),
      ]);
      return { result, goal, me };
    },
  );
  if (result.goal_id !== id || result.item_id !== itemId) notFound();
  const archived = goal.status === "archived";

  return (
    <div className="space-y-8">
      <Link
        href={studyPath(id, itemId)}
        className="inline-flex items-center gap-1.5 rounded-sm text-sm text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
      >
        <ArrowLeftIcon className="size-4" aria-hidden="true" />
        Back to the lesson
      </Link>

      <PageHeader
        eyebrow={<Badge variant="secondary">{result.item_title}</Badge>}
        title={`Results: ${result.quiz_title}`}
      />

      <NoticeBanner code={firstParam(query.notice)} />

      {archived ? (
        <Alert variant="info">
          <InfoIcon aria-hidden="true" />
          <AlertDescription>
            This goal is archived, so your results are read-only. Restore the goal to change your
            marking or take more quizzes.
          </AlertDescription>
        </Alert>
      ) : null}

      <ResultsView
        goalId={id}
        itemId={itemId}
        result={result}
        timeZone={me.timezone}
        readOnly={archived}
      />
    </div>
  );
}
