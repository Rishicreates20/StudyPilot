import { ArrowLeftIcon, InfoIcon } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { connection } from "next/server";
import { Suspense } from "react";

import { EmptyState } from "@/components/feedback/empty-state";
import { NoticeBanner } from "@/components/feedback/notice-banner";
import { PageContainer, PageHeader } from "@/components/layout/page";
import { RegenerateDialog } from "@/components/roadmap/regenerate-dialog";
import { RoadmapView } from "@/components/roadmap/roadmap-view";
import { VersionHistory } from "@/components/roadmap/version-history";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { SubmitButton } from "@/components/forms/submit-button";
import { callApi } from "@/lib/api/call";
import { fetchGoal, fetchGoalJobs, fetchMe, fetchRoadmap, fetchRoadmaps } from "@/lib/api/server";
import { goalPath, isGoalId } from "@/lib/goals/ids";
import { makeRoadmapCurrentAction } from "@/lib/roadmaps/actions";
import { parseVersion, roadmapPath } from "@/lib/roadmaps/paths";
import { firstParam, type SearchParams } from "@/lib/search-params";

export const metadata: Metadata = { title: "Roadmap" };

type RoadmapPageProps = {
  params: Promise<{ id: string }>;
  searchParams: SearchParams;
};

export default function RoadmapPage(props: RoadmapPageProps) {
  return (
    <PageContainer className="max-w-4xl py-10">
      <Suspense
        fallback={
          <div className="space-y-6" role="status" aria-label="Loading the roadmap">
            <Skeleton className="h-10 w-2/3" />
            <Skeleton className="h-40 w-full" />
            <Skeleton className="h-64 w-full" />
          </div>
        }
      >
        <RoadmapContent {...props} />
      </Suspense>
    </PageContainer>
  );
}

async function RoadmapContent({ params, searchParams }: RoadmapPageProps) {
  await connection();
  const { id } = await params;
  if (!isGoalId(id)) notFound();
  const query = await searchParams;
  const requestedVersion = parseVersion(firstParam(query.version));

  // A missing goal and someone else's goal are the same 404.
  const loaded = await callApi(roadmapPath(id), async (accessToken) => {
    const [goal, me, versions, jobs] = await Promise.all([
      fetchGoal(accessToken, id),
      fetchMe(accessToken),
      fetchRoadmaps(accessToken, id),
      fetchGoalJobs(accessToken, id, 1),
    ]);
    const shown = requestedVersion
      ? versions.items.find((version) => version.version === requestedVersion)
      : versions.items.find((version) => version.status === "current");
    // An unknown ?version= is a 404; having no roadmap yet is handled below with a prompt, never a
    // redirect (a redirect seen while this page is prefetched would be replayed later).
    if (requestedVersion && !shown)
      return { goal, me, versions, jobs, roadmap: null, missing: true };
    const roadmap = shown ? await fetchRoadmap(accessToken, shown.id) : null;
    return { goal, me, versions, jobs, roadmap, missing: false };
  });
  if (loaded.missing) notFound();

  const { goal, me, versions, jobs, roadmap } = loaded;
  const archived = goal.status === "archived";
  const generating =
    jobs.items[0] !== undefined && ["queued", "running"].includes(jobs.items[0].status);

  const backLink = (
    <Link
      href={goalPath(goal.id)}
      className="inline-flex items-center gap-1.5 rounded-sm text-sm text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
    >
      <ArrowLeftIcon className="size-4" aria-hidden="true" />
      Back to {goal.title}
    </Link>
  );

  if (!roadmap) {
    return (
      <div className="space-y-6">
        {backLink}
        <PageHeader title="Roadmap" />
        <NoticeBanner code={firstParam(query.notice)} />
        <EmptyState
          title="No roadmap yet"
          description="Generate one from the goal page. It is made in the background."
          action={
            <Button asChild>
              <Link href={goalPath(goal.id)}>Go to the goal</Link>
            </Button>
          }
        />
      </div>
    );
  }

  const isCurrent = roadmap.status === "current";

  return (
    <div className="space-y-8">
      {backLink}

      <PageHeader
        eyebrow={
          <span className="flex flex-wrap items-center gap-2">
            <Badge variant="secondary">Version {roadmap.version}</Badge>
            {isCurrent ? (
              <Badge variant="info">Current</Badge>
            ) : (
              <Badge variant="outline">Earlier version</Badge>
            )}
          </span>
        }
        title={roadmap.title}
        actions={
          archived ? null : (
            <>
              {isCurrent ? null : (
                <form action={makeRoadmapCurrentAction.bind(null, goal.id, roadmap.id)}>
                  <SubmitButton>Make this version current</SubmitButton>
                </form>
              )}
              <RegenerateDialog goalId={goal.id} hasRoadmap />
            </>
          )
        }
      />

      <NoticeBanner code={firstParam(query.notice)} />

      {generating ? (
        <Alert variant="info">
          <InfoIcon aria-hidden="true" />
          <AlertDescription>
            A new version is being made.{" "}
            <Link href={goalPath(goal.id)} className="underline underline-offset-4">
              Follow its progress on the goal page.
            </Link>
          </AlertDescription>
        </Alert>
      ) : null}

      {isCurrent ? null : (
        <Alert variant="info">
          <InfoIcon aria-hidden="true" />
          <AlertDescription>
            You are looking at an earlier version. The current roadmap is version{" "}
            {versions.items.find((version) => version.status === "current")?.version}.
          </AlertDescription>
        </Alert>
      )}

      {archived ? (
        <Alert variant="info">
          <InfoIcon aria-hidden="true" />
          <AlertDescription>
            This goal is archived, so its roadmap is read-only. Restore the goal to revise it.
          </AlertDescription>
        </Alert>
      ) : null}

      <RoadmapView roadmap={roadmap} goalId={goal.id} />

      <VersionHistory
        goalId={goal.id}
        versions={versions.items}
        viewingId={roadmap.id}
        archived={archived}
        timeZone={me.timezone}
      />
    </div>
  );
}
