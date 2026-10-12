import { ArrowLeftIcon, FileTextIcon, InfoIcon } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { connection } from "next/server";
import { Suspense } from "react";

import { AutoRefresh } from "@/components/documents/auto-refresh";
import { DocumentCard } from "@/components/documents/document-card";
import { SearchPanel } from "@/components/documents/search-panel";
import { PasteForm, UploadForm } from "@/components/documents/upload-forms";
import { EmptyState } from "@/components/feedback/empty-state";
import { NoticeBanner } from "@/components/feedback/notice-banner";
import { PageContainer, PageHeader } from "@/components/layout/page";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { callApi } from "@/lib/api/call";
import { fetchDocuments, fetchGoal, fetchMe } from "@/lib/api/server";
import { anyWorking } from "@/lib/documents/state";
import { documentsPath } from "@/lib/documents/paths";
import { goalPath, isGoalId } from "@/lib/goals/ids";
import { firstParam, type SearchParams } from "@/lib/search-params";

export const metadata: Metadata = { title: "Study material" };

type DocumentsPageProps = {
  params: Promise<{ id: string }>;
  searchParams: SearchParams;
};

export default function DocumentsPage(props: DocumentsPageProps) {
  return (
    <PageContainer className="max-w-3xl py-10">
      <Suspense
        fallback={
          <div className="space-y-6" role="status" aria-label="Loading the study material">
            <Skeleton className="h-10 w-2/3" />
            <Skeleton className="h-48 w-full" />
            <Skeleton className="h-48 w-full" />
          </div>
        }
      >
        <DocumentsContent {...props} />
      </Suspense>
    </PageContainer>
  );
}

async function DocumentsContent({ params, searchParams }: DocumentsPageProps) {
  await connection(); // statuses change while the worker runs: never reuse a rendered answer
  const { id } = await params;
  if (!isGoalId(id)) notFound();
  const query = await searchParams;

  // A missing goal and someone else's goal are the same 404.
  const { goal, me, list } = await callApi(documentsPath(id), async (accessToken) => {
    const [goal, me, list] = await Promise.all([
      fetchGoal(accessToken, id),
      fetchMe(accessToken),
      fetchDocuments(accessToken, id),
    ]);
    return { goal, me, list };
  });

  const archived = list.goal_archived;
  const ready = list.items.filter((document) => document.status === "ready").length;
  const canAdd = !archived && list.storage_available && list.indexing_available;

  return (
    <div className="space-y-8">
      {anyWorking(list.items) ? <AutoRefresh /> : null}

      <Link
        href={goalPath(goal.id)}
        className="inline-flex items-center gap-1.5 rounded-sm text-sm text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
      >
        <ArrowLeftIcon className="size-4" aria-hidden="true" />
        Back to {goal.title}
      </Link>

      <PageHeader
        title="Study material"
        description="Upload your notes, textbook chapters or slides. StudyPilot reads them privately, and lessons for this goal are written from them whenever they cover the topic, with the passages cited."
      />

      <NoticeBanner code={firstParam(query.notice)} />

      {archived ? (
        <Alert variant="info">
          <InfoIcon aria-hidden="true" />
          <AlertDescription>
            This goal is archived, so its documents are read-only. Restore the goal to add more.
          </AlertDescription>
        </Alert>
      ) : null}
      {!list.storage_available ? (
        <Alert variant="warning">
          <InfoIcon aria-hidden="true" />
          <AlertDescription>
            File storage isn&rsquo;t set up on this server, so documents can&rsquo;t be added yet.
          </AlertDescription>
        </Alert>
      ) : null}
      {list.storage_available && !list.indexing_available ? (
        <Alert variant="warning">
          <InfoIcon aria-hidden="true" />
          <AlertDescription>
            The AI service isn&rsquo;t set up on this server, so documents can&rsquo;t be read or
            indexed yet.
          </AlertDescription>
        </Alert>
      ) : null}

      {canAdd ? (
        <div className="grid gap-6 md:grid-cols-2">
          <UploadForm
            goalId={goal.id}
            maxBytes={list.limits.max_bytes}
            ocrAvailable={list.ocr_available}
          />
          <PasteForm goalId={goal.id} />
        </div>
      ) : null}

      {ready > 0 ? <SearchPanel goalId={goal.id} /> : null}

      <section aria-labelledby="documents-heading" className="space-y-4">
        <h2 id="documents-heading" className="font-heading text-xl font-semibold tracking-tight">
          Your documents
        </h2>
        {list.items.length === 0 ? (
          <EmptyState
            icon={FileTextIcon}
            headingLevel="h3"
            title="No study material yet"
            description="Add a PDF, a text file, a picture of your notes or some pasted text. Lessons will use it when it covers a topic."
          />
        ) : (
          <ul className="space-y-3">
            {list.items.map((document) => (
              <li key={document.id}>
                <DocumentCard goalId={goal.id} document={document} timeZone={me.timezone} />
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
