import {
  CircleAlertIcon,
  CircleCheckIcon,
  FileImageIcon,
  FileTextIcon,
  LoaderCircleIcon,
  PencilLineIcon,
} from "lucide-react";
import Link from "next/link";

import { ProgressBar } from "@/components/progress/progress-bar";
import { Badge, type BadgeVariant } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import type { DocumentStatus, StudyDocument } from "@/lib/api/server";
import {
  describeDocumentStage,
  documentKindLabel,
  documentStatusLabel,
  documentSummary,
  formatBytes,
} from "@/lib/documents/labels";
import { documentPath } from "@/lib/documents/paths";
import { documentPanelState } from "@/lib/documents/state";
import { formatMoment } from "@/lib/format";

const STATUS_VARIANT: Readonly<Record<DocumentStatus, BadgeVariant>> = {
  queued: "secondary",
  processing: "secondary",
  review: "warning",
  ready: "success",
  failed: "destructive",
};

function StatusIcon({ document }: { document: StudyDocument }) {
  const state = documentPanelState(document).kind;
  if (state === "working")
    return (
      <LoaderCircleIcon
        className="size-3 animate-spin motion-reduce:animate-none"
        aria-hidden="true"
      />
    );
  if (document.status === "ready") return <CircleCheckIcon aria-hidden="true" />;
  if (document.status === "review") return <PencilLineIcon aria-hidden="true" />;
  if (state === "failed" || state === "stopped") return <CircleAlertIcon aria-hidden="true" />;
  return null;
}

/** One document in the list: what it is, where it stands, and a way in. */
export function DocumentCard({
  goalId,
  document,
  timeZone,
}: {
  goalId: string;
  document: StudyDocument;
  timeZone: string;
}) {
  const state = documentPanelState(document);
  const Icon = document.kind === "image" ? FileImageIcon : FileTextIcon;
  const summary = documentSummary(document);

  return (
    <Card>
      <CardContent className="space-y-3 pt-6">
        <div className="flex items-start gap-3">
          <Icon className="mt-1 size-5 shrink-0 text-primary" aria-hidden="true" />
          <div className="min-w-0 flex-1 space-y-1">
            <h3 className="font-heading text-base leading-snug font-semibold break-words">
              <Link
                href={documentPath(goalId, document.id)}
                className="rounded-sm underline-offset-4 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
              >
                {document.title}
              </Link>
            </h3>
            <p className="text-sm text-muted-foreground">
              {documentKindLabel(document.kind)} · {formatBytes(document.size_bytes)} · added{" "}
              {formatMoment(document.created_at, timeZone)}
              {summary ? ` · ${summary}` : ""}
            </p>
          </div>
          <Badge variant={STATUS_VARIANT[document.status]}>
            <StatusIcon document={document} />
            {documentStatusLabel(document.status)}
          </Badge>
        </div>

        {state.kind === "working" ? (
          <ProgressBar
            label={describeDocumentStage(state.job)}
            value={state.job.progress}
            className="pl-8"
          />
        ) : null}
        {state.kind === "failed" ? (
          <p className="pl-8 text-sm text-destructive-foreground">{state.message}</p>
        ) : null}
        {state.kind === "stopped" ? (
          <p className="pl-8 text-sm text-muted-foreground">
            Processing was stopped. Open the document to process it again.
          </p>
        ) : null}
        {state.kind === "review" ? (
          <p className="pl-8 text-sm text-warning-foreground">
            Some text was read from a picture. Check it before it is used.
          </p>
        ) : null}
        {document.status === "ready" && document.warnings.length > 0 ? (
          <p className="pl-8 text-sm text-muted-foreground">
            {document.warnings.length === 1
              ? "1 note about how this was read."
              : `${document.warnings.length} notes about how this was read.`}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}
