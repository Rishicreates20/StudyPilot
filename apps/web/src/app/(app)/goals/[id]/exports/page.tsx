import { ArrowLeftIcon, FolderDownIcon, InfoIcon } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { connection } from "next/server";
import { Suspense } from "react";

import { AutoRefresh } from "@/components/documents/auto-refresh";
import { ExportCard } from "@/components/exports/export-card";
import { EmptyState } from "@/components/feedback/empty-state";
import { NoticeBanner } from "@/components/feedback/notice-banner";
import { PageContainer, PageHeader } from "@/components/layout/page";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { callApi } from "@/lib/api/call";
import { fetchExports, fetchGoal, fetchMe } from "@/lib/api/server";
import { anyProcessing } from "@/lib/exports/labels";
import { exportsPath } from "@/lib/exports/paths";
import { goalPath, isGoalId } from "@/lib/goals/ids";
import { roadmapPath } from "@/lib/roadmaps/paths";
import { firstParam, type SearchParams } from "@/lib/search-params";

export const metadata: Metadata = { title: "Exported files" };

type ExportsPageProps = {
  params: Promise<{ id: string }>;
  searchParams: SearchParams;
};

export default function ExportsPage(props: ExportsPageProps) {
  return (
    <PageContainer className="max-w-3xl py-10">
      <Suspense
        fallback={
          <div className="space-y-6" role="status" aria-label="Loading your exported files">
            <Skeleton className="h-10 w-2/3" />
            <Skeleton className="h-32 w-full" />
            <Skeleton className="h-32 w-full" />
          </div>
        }
      >
        <ExportsContent {...props} />
      </Suspense>
    </PageContainer>
  );
}

async function ExportsContent({ params, searchParams }: ExportsPageProps) {
  await connection(); // statuses change while the worker runs: never reuse a rendered answer
  const { id } = await params;
  if (!isGoalId(id)) notFound();
  const query = await searchParams;

  // A missing goal and someone else's goal are the same 404.
  const { goal, me, list } = await callApi(exportsPath(id), async (accessToken) => {
    const [goal, me, list] = await Promise.all([
      fetchGoal(accessToken, id),
      fetchMe(accessToken),
      fetchExports(accessToken, id),
    ]);
    return { goal, me, list };
  });
  const archived = goal.status === "archived";

  return (
    <div className="space-y-8">
      {anyProcessing(list.items) ? <AutoRefresh /> : null}

      <Link
        href={goalPath(goal.id)}
        className="inline-flex items-center gap-1.5 rounded-sm text-sm text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
      >
        <ArrowLeftIcon className="size-4" aria-hidden="true" />
        Back to {goal.title}
      </Link>

      <PageHeader
        title="Exported files"
        description="PDF notes, revision sheets, roadmaps and slides made from this goal's lessons and roadmaps. Files are private to you, and each download link works only for a couple of minutes."
      />

      <NoticeBanner code={firstParam(query.notice)} />

      {archived ? (
        <Alert variant="info">
          <InfoIcon aria-hidden="true" />
          <AlertDescription>
            This goal is archived. You can still download and delete files made earlier.
          </AlertDescription>
        </Alert>
      ) : null}

      <section aria-labelledby="exports-heading" className="space-y-4">
        <h2 id="exports-heading" className="sr-only">
          Your files
        </h2>
        {list.items.length === 0 ? (
          <EmptyState
            icon={FolderDownIcon}
            headingLevel="h3"
            title="No files yet"
            description="Open a lesson or your roadmap and choose Download a copy. The file is made in a few seconds and appears here."
            action={
              <Link
                href={roadmapPath(goal.id)}
                className="text-sm text-primary underline-offset-4 hover:underline"
              >
                Go to the roadmap
              </Link>
            }
          />
        ) : (
          <ul className="space-y-3">
            {list.items.map((item) => (
              <li key={item.id}>
                <ExportCard
                  goalId={goal.id}
                  item={item}
                  timeZone={me.timezone}
                  readOnly={archived}
                />
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
