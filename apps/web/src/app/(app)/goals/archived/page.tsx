import { ArchiveIcon, ArrowLeftIcon } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";
import { Suspense } from "react";

import { EmptyState } from "@/components/feedback/empty-state";
import { CardGridSkeleton } from "@/components/feedback/loading-state";
import { NoticeBanner } from "@/components/feedback/notice-banner";
import { GoalList } from "@/components/goals/goal-list";
import { PageContainer, PageHeader } from "@/components/layout/page";
import { Button } from "@/components/ui/button";
import { callApi } from "@/lib/api/call";
import { ApiError, fetchGoals } from "@/lib/api/server";
import { DASHBOARD_PATH } from "@/lib/auth/paths";
import { firstParam, type SearchParams } from "@/lib/search-params";

export const metadata: Metadata = { title: "Archived goals" };

const ARCHIVED_PATH = "/goals/archived";
const PAGE_SIZE = 12;

export default function ArchivedGoalsPage({ searchParams }: { searchParams: SearchParams }) {
  return (
    <PageContainer className="py-10">
      <Suspense fallback={<CardGridSkeleton count={3} label="Loading archived goals" />}>
        <ArchivedContent searchParams={searchParams} />
      </Suspense>
    </PageContainer>
  );
}

async function ArchivedContent({ searchParams }: { searchParams: SearchParams }) {
  const params = await searchParams;
  const cursor = firstParam(params.cursor);

  let page;
  try {
    page = await callApi(ARCHIVED_PATH, (accessToken) =>
      fetchGoals(accessToken, {
        status: ["archived"],
        limit: PAGE_SIZE,
        ...(cursor ? { cursor } : {}),
      }),
    );
  } catch (error) {
    // A stale or hand-edited cursor: start from the newest.
    if (error instanceof ApiError && error.code === "INVALID_CURSOR") redirect(ARCHIVED_PATH);
    throw error;
  }

  return (
    <div className="space-y-8">
      <Link
        href={DASHBOARD_PATH}
        className="inline-flex items-center gap-1.5 rounded-sm text-sm text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
      >
        <ArrowLeftIcon className="size-4" aria-hidden="true" />
        All goals
      </Link>

      <PageHeader
        title="Archived goals"
        description="Goals you put away. Open one to restore it, or to delete it for good."
      />

      <NoticeBanner code={firstParam(params.notice)} />

      {page.items.length > 0 ? (
        <GoalList
          label="Archived goals"
          goals={page.items}
          nextHref={
            page.next_cursor
              ? `${ARCHIVED_PATH}?cursor=${encodeURIComponent(page.next_cursor)}`
              : undefined
          }
          firstHref={cursor ? ARCHIVED_PATH : undefined}
        />
      ) : (
        <EmptyState
          icon={ArchiveIcon}
          headingLevel="h2"
          title="Nothing archived"
          description="When you archive a goal it waits here until you restore or delete it."
          action={
            <Button asChild variant="outline">
              <Link href={DASHBOARD_PATH}>Back to your goals</Link>
            </Button>
          }
        />
      )}
    </div>
  );
}
