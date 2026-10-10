import { CircleCheckIcon, PlusIcon, TargetIcon } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";
import { Suspense } from "react";

import { EmptyState } from "@/components/feedback/empty-state";
import { LoadError } from "@/components/feedback/load-error";
import { CardGridSkeleton } from "@/components/feedback/loading-state";
import { GoalCard } from "@/components/goals/goal-card";
import { PageContainer, PageHeader } from "@/components/layout/page";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, fetchGoals, fetchMe, type GoalPage, type Me } from "@/lib/api/server";
import { DASHBOARD_PATH, sessionEndedUrlFor } from "@/lib/auth/paths";
import { requireApiSession } from "@/lib/auth/session";
import { firstParam, type SearchParams } from "@/lib/search-params";

export const metadata: Metadata = { title: "Your goals" };

const PAGE_SIZE = 12;

export default function DashboardPage({ searchParams }: { searchParams: SearchParams }) {
  return (
    <PageContainer className="py-10">
      <Suspense
        fallback={
          <div className="space-y-8">
            <Skeleton className="h-24 w-full max-w-xl" />
            <CardGridSkeleton count={3} label="Loading your goals" />
          </div>
        }
      >
        <DashboardContent searchParams={searchParams} />
      </Suspense>
    </PageContainer>
  );
}

async function DashboardContent({ searchParams }: { searchParams: SearchParams }) {
  const params = await searchParams;
  const cursor = firstParam(params.cursor);
  const justCreated = firstParam(params.created) === "1";
  const retryHref = cursor
    ? `${DASHBOARD_PATH}?cursor=${encodeURIComponent(cursor)}`
    : DASHBOARD_PATH;

  const { accessToken } = await requireApiSession(retryHref);

  let me: Me;
  let page: GoalPage;
  try {
    [me, page] = await Promise.all([
      fetchMe(accessToken),
      fetchGoals(accessToken, { limit: PAGE_SIZE, ...(cursor ? { cursor } : {}) }),
    ]);
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    // The API did not accept the session (expired, revoked, deleted account): sign in again.
    if (error.isUnauthenticated) redirect(sessionEndedUrlFor(DASHBOARD_PATH));
    // A stale or hand-edited cursor: start from the newest goals.
    if (error.code === "INVALID_CURSOR") redirect(DASHBOARD_PATH);
    return (
      <LoadError
        title="We couldn't load your goals"
        description={
          error.status === 0 || error.status === 503
            ? "The learning service is temporarily unavailable. Your goals are safe."
            : "Something went wrong while loading your goals."
        }
        retryHref={retryHref}
        reference={error.requestId}
      />
    );
  }

  const name = me.display_name ?? me.email?.split("@")[0] ?? "there";

  return (
    <div className="space-y-8">
      <PageHeader
        title="Your learning goals"
        description={`Welcome back, ${name}. Pick up a goal or start a new one.`}
        actions={
          <Button asChild size="lg">
            <Link href="/goals/new">
              <PlusIcon aria-hidden="true" />
              New goal
            </Link>
          </Button>
        }
      />

      {justCreated ? (
        <Alert variant="success">
          <CircleCheckIcon aria-hidden="true" />
          <AlertTitle>Goal created</AlertTitle>
          <AlertDescription>It is saved to your account and shown below.</AlertDescription>
        </Alert>
      ) : null}

      {page.items.length === 0 && !cursor ? (
        <EmptyState
          icon={TargetIcon}
          headingLevel="h2"
          title="You don't have any goals yet"
          description="Tell us what you want to learn, how much time you have and when you need to be ready."
          action={
            <Button asChild size="lg">
              <Link href="/goals/new">
                <PlusIcon aria-hidden="true" />
                Create your first goal
              </Link>
            </Button>
          }
        />
      ) : (
        <section aria-labelledby="goals-heading" className="space-y-6">
          <h2 id="goals-heading" className="sr-only">
            Goals
          </h2>
          <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {page.items.map((goal) => (
              <li key={goal.id}>
                <GoalCard goal={goal} />
              </li>
            ))}
          </ul>
          <nav aria-label="Goal pages" className="flex flex-wrap justify-center gap-3">
            {cursor ? (
              <Button asChild variant="outline">
                <Link href={DASHBOARD_PATH}>Back to newest goals</Link>
              </Button>
            ) : null}
            {page.next_cursor ? (
              <Button asChild variant="outline">
                <Link href={`${DASHBOARD_PATH}?cursor=${encodeURIComponent(page.next_cursor)}`}>
                  Show older goals
                </Link>
              </Button>
            ) : null}
          </nav>
        </section>
      )}
    </div>
  );
}
