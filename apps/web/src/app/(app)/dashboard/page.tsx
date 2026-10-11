import {
  ArchiveIcon,
  CircleCheckIcon,
  PauseIcon,
  PlusIcon,
  SparklesIcon,
  TargetIcon,
  ZapIcon,
} from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";
import { Suspense } from "react";

import { EmptyState } from "@/components/feedback/empty-state";
import { LoadError } from "@/components/feedback/load-error";
import { CardGridSkeleton } from "@/components/feedback/loading-state";
import { NoticeBanner } from "@/components/feedback/notice-banner";
import { GoalList } from "@/components/goals/goal-list";
import { DashboardProgress } from "@/components/quiz/dashboard-progress";
import { StatCard } from "@/components/goals/stat-card";
import { PageContainer, PageHeader } from "@/components/layout/page";
import { Alert, AlertAction, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  ApiError,
  fetchGoalSummary,
  fetchGoals,
  fetchMe,
  type GoalPage,
  type GoalSummary,
  type Me,
} from "@/lib/api/server";
import { DASHBOARD_PATH, sessionEndedUrlFor } from "@/lib/auth/paths";
import { requireApiSession } from "@/lib/auth/session";
import { ONBOARDING_PATH } from "@/lib/onboarding/paths";
import { firstParam, type SearchParams } from "@/lib/search-params";

export const metadata: Metadata = { title: "Your goals" };

const IN_PROGRESS_PAGE_SIZE = 12;
const COMPLETED_PAGE_SIZE = 6;

/** A dashboard URL that keeps the position in both lists (each list pages on its own). */
function dashboardHref(position: {
  cursor?: string | undefined;
  completedCursor?: string | undefined;
}) {
  const query = new URLSearchParams();
  if (position.cursor) query.set("cursor", position.cursor);
  if (position.completedCursor) query.set("completed_cursor", position.completedCursor);
  const text = query.toString();
  return text ? `${DASHBOARD_PATH}?${text}` : DASHBOARD_PATH;
}

export default function DashboardPage({ searchParams }: { searchParams: SearchParams }) {
  return (
    <PageContainer className="py-10">
      <Suspense
        fallback={
          <div className="space-y-8" role="status" aria-label="Loading your goals">
            <Skeleton className="h-24 w-full max-w-xl" />
            <div className="grid gap-4 sm:grid-cols-3">
              <Skeleton className="h-24" />
              <Skeleton className="h-24" />
              <Skeleton className="h-24" />
            </div>
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
  const completedCursor = firstParam(params.completed_cursor);
  const retryHref = dashboardHref({ cursor, completedCursor });

  const { accessToken } = await requireApiSession(retryHref);

  let me: Me;
  let summary: GoalSummary;
  let inProgress: GoalPage;
  let completed: GoalPage;
  try {
    [me, summary, inProgress, completed] = await Promise.all([
      fetchMe(accessToken),
      fetchGoalSummary(accessToken),
      fetchGoals(accessToken, {
        status: ["active", "paused"],
        limit: IN_PROGRESS_PAGE_SIZE,
        ...(cursor ? { cursor } : {}),
      }),
      fetchGoals(accessToken, {
        status: ["completed"],
        limit: COMPLETED_PAGE_SIZE,
        ...(completedCursor ? { cursor: completedCursor } : {}),
      }),
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

  // Someone who hasn't finished (or skipped) the short setup is invited to, not sent to it. A
  // redirect here would be recorded by Next's client router when it prefetches this page from the
  // header link, and replayed later, even after setup is done, sending people back to onboarding.
  const setupDue = !me.onboarding_completed;

  const name = me.display_name ?? me.email?.split("@")[0] ?? "there";
  const hasAnyGoals = summary.active + summary.paused + summary.completed + summary.archived > 0;

  return (
    <div className="space-y-10">
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

      <NoticeBanner code={firstParam(params.notice)} />

      {setupDue ? (
        <Alert variant="info">
          <SparklesIcon aria-hidden="true" />
          <AlertTitle>Finish setting up StudyPilot</AlertTitle>
          <AlertDescription>
            Two quick questions about how you like to study make new goals fit you from the start.
          </AlertDescription>
          <AlertAction>
            <Button asChild size="sm">
              <Link href={ONBOARDING_PATH}>Continue setup</Link>
            </Button>
          </AlertAction>
        </Alert>
      ) : null}

      {!hasAnyGoals ? (
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
        <>
          <section aria-label="Your goals at a glance" className="grid gap-4 sm:grid-cols-3">
            <StatCard label="Active" value={summary.active} icon={ZapIcon} />
            <StatCard label="Paused" value={summary.paused} icon={PauseIcon} />
            <StatCard label="Completed" value={summary.completed} icon={CircleCheckIcon} />
          </section>

          <Suspense fallback={<Skeleton className="h-40 w-full" />}>
            <DashboardProgress goals={inProgress.items} />
          </Suspense>

          <section aria-labelledby="in-progress-heading" className="space-y-6">
            <h2 id="in-progress-heading" className="text-xl font-semibold tracking-tight">
              In progress
            </h2>
            {inProgress.items.length > 0 ? (
              <GoalList
                label="Goals in progress"
                goals={inProgress.items}
                nextHref={
                  inProgress.next_cursor
                    ? dashboardHref({ cursor: inProgress.next_cursor, completedCursor })
                    : undefined
                }
                firstHref={cursor ? dashboardHref({ completedCursor }) : undefined}
              />
            ) : (
              <EmptyState
                headingLevel="h3"
                title="Nothing in progress"
                description={
                  cursor
                    ? "That was the last of your goals in progress."
                    : "Start a new goal, or resume one you paused."
                }
                action={
                  <Button asChild variant="outline">
                    <Link href={cursor ? dashboardHref({ completedCursor }) : "/goals/new"}>
                      {cursor ? "Back to newest" : "Create a goal"}
                    </Link>
                  </Button>
                }
              />
            )}
          </section>

          {completed.items.length > 0 || completedCursor ? (
            <section aria-labelledby="completed-heading" className="space-y-6">
              <h2 id="completed-heading" className="text-xl font-semibold tracking-tight">
                Completed
              </h2>
              <GoalList
                label="Completed goals"
                goals={completed.items}
                nextHref={
                  completed.next_cursor
                    ? dashboardHref({ cursor, completedCursor: completed.next_cursor })
                    : undefined
                }
                firstHref={completedCursor ? dashboardHref({ cursor }) : undefined}
              />
            </section>
          ) : null}

          {summary.archived > 0 ? (
            <p className="text-sm text-muted-foreground">
              <ArchiveIcon className="mr-1.5 inline size-4 align-text-bottom" aria-hidden="true" />
              You have {summary.archived} archived {summary.archived === 1 ? "goal" : "goals"}.{" "}
              <Link
                href="/goals/archived"
                className="font-medium text-primary underline-offset-4 hover:underline"
              >
                View archive
              </Link>
            </p>
          ) : null}
        </>
      )}
    </div>
  );
}
