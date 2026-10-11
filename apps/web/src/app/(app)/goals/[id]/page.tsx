import { ArchiveIcon, ArrowLeftIcon } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { connection } from "next/server";
import { notFound } from "next/navigation";
import { Suspense } from "react";

import { NoticeBanner } from "@/components/feedback/notice-banner";
import { GoalActions } from "@/components/goals/goal-actions";
import { GoalDetails } from "@/components/goals/goal-details";
import { GoalStatusBadge } from "@/components/goals/goal-status-badge";
import { PageContainer, PageHeader } from "@/components/layout/page";
import { ProgressSection, ProgressSectionSkeleton } from "@/components/quiz/progress-section";
import { RoadmapSection, RoadmapSectionSkeleton } from "@/components/roadmap/roadmap-section";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { callApi } from "@/lib/api/call";
import { fetchGoal, fetchMe } from "@/lib/api/server";
import { DASHBOARD_PATH } from "@/lib/auth/paths";
import { daysBetween, todayIn } from "@/lib/format";
import { goalPath, isGoalId } from "@/lib/goals/ids";
import { goalTypeLabel } from "@/lib/goals/options";
import { firstParam, type SearchParams } from "@/lib/search-params";

export const metadata: Metadata = { title: "Goal" };

type GoalPageProps = {
  params: Promise<{ id: string }>;
  searchParams: SearchParams;
};

export default function GoalPage(props: GoalPageProps) {
  return (
    <PageContainer className="max-w-3xl py-10">
      <Suspense
        fallback={
          <div className="space-y-6" role="status" aria-label="Loading the goal">
            <Skeleton className="h-10 w-2/3" />
            <Skeleton className="h-64 w-full" />
          </div>
        }
      >
        <GoalContent {...props} />
      </Suspense>
    </PageContainer>
  );
}

async function GoalContent({ params, searchParams }: GoalPageProps) {
  await connection(); // "today" and the timestamps depend on the request, never on the build
  const { id } = await params;
  if (!isGoalId(id)) notFound();
  const query = await searchParams;

  // Another user's goal and a missing goal are the same 404 (the API does not tell them apart).
  const [goal, me] = await callApi(goalPath(id), (accessToken) =>
    Promise.all([fetchGoal(accessToken, id), fetchMe(accessToken)]),
  );

  const daysToTarget = goal.target_date
    ? daysBetween(todayIn(me.timezone), goal.target_date)
    : null;
  const archived = goal.status === "archived";

  return (
    <div className="space-y-6">
      <Link
        href={archived ? "/goals/archived" : DASHBOARD_PATH}
        className="inline-flex items-center gap-1.5 rounded-sm text-sm text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
      >
        <ArrowLeftIcon className="size-4" aria-hidden="true" />
        {archived ? "Archived goals" : "All goals"}
      </Link>

      <PageHeader
        eyebrow={
          <span className="flex items-center gap-2">
            <GoalStatusBadge status={goal.status} />
            <span className="text-sm text-muted-foreground">{goalTypeLabel(goal.goal_type)}</span>
          </span>
        }
        title={goal.title}
        className="sm:items-start"
      />

      <GoalActions goalId={goal.id} status={goal.status} />

      <NoticeBanner code={firstParam(query.notice)} />

      {archived ? (
        <Alert variant="info">
          <ArchiveIcon aria-hidden="true" />
          <AlertDescription>
            This goal is archived, so it is read-only. Restore it to edit it or pick it up again.
          </AlertDescription>
        </Alert>
      ) : null}

      <GoalDetails goal={goal} timeZone={me.timezone} daysToTarget={daysToTarget} />

      <Suspense fallback={<RoadmapSectionSkeleton />}>
        <RoadmapSection goalId={goal.id} goalStatus={goal.status} timeZone={me.timezone} />
      </Suspense>

      <Suspense fallback={<ProgressSectionSkeleton />}>
        <ProgressSection goalId={goal.id} goalStatus={goal.status} />
      </Suspense>
    </div>
  );
}
