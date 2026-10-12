import {
  ArrowLeftIcon,
  CircleAlertIcon,
  CircleCheckIcon,
  InfoIcon,
  RotateCcwIcon,
} from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { connection } from "next/server";
import { Suspense } from "react";

import { DocumentActions, RenameForm } from "@/components/documents/document-actions";
import { DocumentWorking } from "@/components/documents/document-working";
import { PagesView } from "@/components/documents/pages-view";
import { NoticeBanner } from "@/components/feedback/notice-banner";
import { SubmitButton } from "@/components/forms/submit-button";
import { PageContainer, PageHeader } from "@/components/layout/page";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { callApi } from "@/lib/api/call";
import { fetchDocument, fetchDocumentPages, fetchGoal, fetchMe } from "@/lib/api/server";
import { confirmDocumentAction, reprocessDocumentAction } from "@/lib/documents/actions";
import {
  documentKindLabel,
  documentStatusLabel,
  documentSummary,
  formatBytes,
} from "@/lib/documents/labels";
import { documentPath, documentsPath } from "@/lib/documents/paths";
import { documentPanelState } from "@/lib/documents/state";
import { formatMoment } from "@/lib/format";
import { isGoalId } from "@/lib/goals/ids";
import { firstParam, type SearchParams } from "@/lib/search-params";

export const metadata: Metadata = { title: "Document" };

const PAGE_SIZE = 20;

type DocumentPageProps = {
  params: Promise<{ id: string; documentId: string }>;
  searchParams: SearchParams;
};

export default function DocumentPage(props: DocumentPageProps) {
  return (
    <PageContainer className="max-w-3xl py-10">
      <Suspense
        fallback={
          <div className="space-y-6" role="status" aria-label="Loading the document">
            <Skeleton className="h-10 w-2/3" />
            <Skeleton className="h-32 w-full" />
            <Skeleton className="h-64 w-full" />
          </div>
        }
      >
        <DocumentContent {...props} />
      </Suspense>
    </PageContainer>
  );
}

function parseOffset(value: string | undefined): number {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed >= 0 && parsed <= 100_000 ? parsed : 0;
}

async function DocumentContent({ params, searchParams }: DocumentPageProps) {
  await connection();
  const { id, documentId } = await params;
  if (!isGoalId(id) || !isGoalId(documentId)) notFound();
  const query = await searchParams;
  const offset = parseOffset(firstParam(query.offset));

  // A missing document and someone else's document are the same 404.
  const { document, pages, goal, me } = await callApi(
    documentPath(id, documentId),
    async (accessToken) => {
      const document = await fetchDocument(accessToken, documentId);
      // The URL names the goal as well as the document; they must belong together.
      if (document.goal_id !== id) notFound();
      const [pages, goal, me] = await Promise.all([
        fetchDocumentPages(accessToken, documentId, offset, PAGE_SIZE),
        fetchGoal(accessToken, id),
        fetchMe(accessToken),
      ]);
      return { document, pages, goal, me };
    },
  );

  const state = documentPanelState(document);
  const archived = goal.status === "archived";
  const busy = state.kind === "working";
  const summary = documentSummary(document);

  return (
    <div className="space-y-8">
      <Link
        href={documentsPath(id)}
        className="inline-flex items-center gap-1.5 rounded-sm text-sm text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
      >
        <ArrowLeftIcon className="size-4" aria-hidden="true" />
        Study material
      </Link>

      <PageHeader
        eyebrow={
          <span className="flex flex-wrap items-center gap-2">
            <Badge variant="secondary">{documentKindLabel(document.kind)}</Badge>
            <Badge
              variant={
                document.status === "ready"
                  ? "success"
                  : document.status === "failed"
                    ? "destructive"
                    : document.status === "review"
                      ? "warning"
                      : "secondary"
              }
            >
              {documentStatusLabel(document.status)}
            </Badge>
          </span>
        }
        title={document.title}
        description={`${document.original_name ? `${document.original_name} · ` : ""}${formatBytes(document.size_bytes)} · added ${formatMoment(document.created_at, me.timezone)}${summary ? ` · ${summary}` : ""}`}
      />

      <NoticeBanner code={firstParam(query.notice)} />

      {archived ? (
        <Alert variant="info">
          <InfoIcon aria-hidden="true" />
          <AlertDescription>
            This goal is archived, so its documents are read-only.
          </AlertDescription>
        </Alert>
      ) : null}

      {state.kind === "working" ? (
        <DocumentWorking goalId={id} documentId={documentId} job={state.job} />
      ) : null}

      {state.kind === "ready" ? (
        <Alert variant="success">
          <CircleCheckIcon aria-hidden="true" />
          <AlertTitle>Ready to use</AlertTitle>
          <AlertDescription>
            {document.chunk_count} passages are indexed. Lessons for this goal can now draw on this
            document, and you can search it from the study material page.
          </AlertDescription>
        </Alert>
      ) : null}

      {state.kind === "failed" ? (
        <div className="space-y-3">
          <Alert variant="destructive">
            <CircleAlertIcon aria-hidden="true" />
            <AlertTitle>This document couldn&rsquo;t be processed</AlertTitle>
            <AlertDescription>
              <p>{state.message}</p>
            </AlertDescription>
          </Alert>
          {!archived ? (
            <div className="flex flex-wrap gap-2">
              {pages.total > 0 ? (
                <form action={confirmDocumentAction.bind(null, id, documentId)}>
                  <SubmitButton>Try indexing again</SubmitButton>
                </form>
              ) : null}
              <form action={reprocessDocumentAction.bind(null, id, documentId)}>
                <SubmitButton variant={pages.total > 0 ? "outline" : "default"}>
                  <RotateCcwIcon aria-hidden="true" />
                  Process again
                </SubmitButton>
              </form>
            </div>
          ) : null}
        </div>
      ) : null}

      {state.kind === "stopped" ? (
        <div className="space-y-3">
          <Alert variant="info">
            <InfoIcon aria-hidden="true" />
            <AlertTitle>Processing was stopped</AlertTitle>
            <AlertDescription>Process the document again to read and index it.</AlertDescription>
          </Alert>
          {!archived ? (
            <form action={reprocessDocumentAction.bind(null, id, documentId)}>
              <SubmitButton>
                <RotateCcwIcon aria-hidden="true" />
                Process again
              </SubmitButton>
            </form>
          ) : null}
        </div>
      ) : null}

      {state.kind === "review" ? (
        <Alert variant="warning">
          <CircleAlertIcon aria-hidden="true" />
          <AlertTitle>Check what was read before it is used</AlertTitle>
          <AlertDescription>
            <p>
              Some of this text was read from a picture by an AI model, and it may have misread
              words, especially in handwriting. Compare it with your original, correct anything
              wrong, then use the text. Nothing is searchable or cited until you do.
            </p>
            {!archived ? (
              <form action={confirmDocumentAction.bind(null, id, documentId)} className="mt-3">
                <SubmitButton>
                  <CircleCheckIcon aria-hidden="true" />
                  Use this text
                </SubmitButton>
              </form>
            ) : null}
          </AlertDescription>
        </Alert>
      ) : null}

      {document.warnings.length > 0 ? (
        <section aria-labelledby="notes-heading" className="space-y-2">
          <h2 id="notes-heading" className="font-heading text-xl font-semibold tracking-tight">
            Notes about how this was read
          </h2>
          <ul className="space-y-2">
            {document.warnings.map((warning, index) => (
              <li
                key={`${warning.code}-${index}`}
                className="flex items-start gap-2 rounded-lg border bg-card p-3 text-sm"
              >
                <InfoIcon
                  className="mt-0.5 size-4 shrink-0 text-warning-foreground"
                  aria-hidden="true"
                />
                <span>{warning.message}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <section aria-labelledby="text-heading" className="space-y-4">
        <h2 id="text-heading" className="font-heading text-xl font-semibold tracking-tight">
          Extracted text
        </h2>
        <PagesView
          goalId={id}
          documentId={documentId}
          pages={pages}
          paginated={document.paginated}
        />
      </section>

      {!archived ? (
        <section aria-labelledby="manage-heading" className="space-y-4">
          <h2 id="manage-heading" className="font-heading text-xl font-semibold tracking-tight">
            Manage
          </h2>
          <RenameForm goalId={id} documentId={documentId} title={document.title} />
          <DocumentActions goalId={id} documentId={documentId} busy={busy} readOnly={archived} />
        </section>
      ) : (
        <DocumentActions goalId={id} documentId={documentId} busy readOnly />
      )}
    </div>
  );
}
