import {
  CircleAlertIcon,
  CircleCheckIcon,
  DownloadIcon,
  FileTextIcon,
  LoaderCircleIcon,
  PresentationIcon,
  RotateCcwIcon,
  Trash2Icon,
} from "lucide-react";

import { SubmitButton } from "@/components/forms/submit-button";
import { ProgressBar } from "@/components/progress/progress-bar";
import { Badge, type BadgeVariant } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import type { Export, ExportStatus } from "@/lib/api/server";
import {
  deleteExportAction,
  requestLessonExportAction,
  requestRoadmapExportAction,
} from "@/lib/exports/actions";
import {
  FORMAT_LABELS,
  STATUS_LABELS,
  describeExportStage,
  formatBytes,
  isLessonFormat,
  isRoadmapFormat,
  pagesLabel,
} from "@/lib/exports/labels";
import { exportDownloadPath, exportsPath } from "@/lib/exports/paths";
import { formatMoment } from "@/lib/format";

const STATUS_VARIANT: Readonly<Record<ExportStatus, BadgeVariant>> = {
  ready: "success",
  processing: "secondary",
  failed: "destructive",
  not_started: "outline",
};

function StatusIcon({ status }: { status: ExportStatus }) {
  if (status === "processing")
    return (
      <LoaderCircleIcon
        className="size-3 animate-spin motion-reduce:animate-none"
        aria-hidden="true"
      />
    );
  if (status === "ready") return <CircleCheckIcon aria-hidden="true" />;
  if (status === "failed") return <CircleAlertIcon aria-hidden="true" />;
  return null;
}

/** The action that asks for the same file again (after a failure). */
function retryAction(goalId: string, item: Export) {
  const page = exportsPath(goalId);
  if (item.lesson_id && isLessonFormat(item.format))
    return requestLessonExportAction.bind(null, goalId, item.lesson_id, page);
  if (item.roadmap_id && isRoadmapFormat(item.format))
    return requestRoadmapExportAction.bind(null, goalId, item.roadmap_id, page);
  return null;
}

/** One exported file: what it is, what it was made from, where it stands, and what can be done. */
export function ExportCard({
  goalId,
  item,
  timeZone,
  readOnly,
}: {
  goalId: string;
  item: Export;
  timeZone: string;
  readOnly: boolean;
}) {
  const label = FORMAT_LABELS[item.format];
  const Icon = item.format === "slides_pptx" ? PresentationIcon : FileTextIcon;
  const source = `${item.lesson_id ? "Lesson" : "Roadmap"} "${item.source_title}", version ${item.source_version}`;
  const details = [
    item.size_bytes != null ? formatBytes(item.size_bytes) : null,
    pagesLabel(item),
    item.ready_at ? `made ${formatMoment(item.ready_at, timeZone)}` : null,
  ].filter(Boolean);
  const retry = item.status === "failed" && !readOnly ? retryAction(goalId, item) : null;
  const busy = item.status === "processing";

  return (
    <Card>
      <CardContent className="space-y-3 pt-6">
        <div className="flex items-start gap-3">
          <Icon className="mt-1 size-5 shrink-0 text-primary" aria-hidden="true" />
          <div className="min-w-0 flex-1 space-y-1">
            <h3 className="font-heading text-base leading-snug font-semibold">{label.title}</h3>
            <p className="text-sm break-words text-muted-foreground">{source}</p>
            {details.length > 0 ? (
              <p className="text-sm text-muted-foreground">{details.join(" · ")}</p>
            ) : null}
          </div>
          <Badge variant={STATUS_VARIANT[item.status]}>
            <StatusIcon status={item.status} />
            {STATUS_LABELS[item.status]}
          </Badge>
        </div>

        {busy && item.job ? (
          <ProgressBar
            label={describeExportStage(item.job.stage)}
            value={item.job.progress}
            className="pl-8"
          />
        ) : null}
        {item.status === "failed" && item.job?.error_message ? (
          <p className="pl-8 text-sm text-destructive-foreground">{item.job.error_message}</p>
        ) : null}
        {item.status === "ready" && (item.unsupported_characters ?? 0) > 0 ? (
          <p className="pl-8 text-sm text-warning-foreground">
            {item.unsupported_characters === 1
              ? "1 character couldn't be shown in this file's fonts and was replaced with a placeholder mark."
              : `${item.unsupported_characters} characters couldn't be shown in this file's fonts and were replaced with a placeholder mark.`}
          </p>
        ) : null}

        <div className="flex flex-wrap items-center gap-2 pl-8">
          {item.status === "ready" ? (
            // A plain link, never prefetched: the route mints a short-lived signed link on click.
            <a
              href={exportDownloadPath(goalId, item.id)}
              className={buttonVariants({ size: "sm" })}
              aria-label={`Download ${label.title}: ${item.source_title}`}
            >
              <DownloadIcon aria-hidden="true" />
              Download
            </a>
          ) : null}
          {retry ? (
            <form action={retry}>
              <input type="hidden" name="format" value={item.format} />
              <SubmitButton size="sm" variant="outline">
                <RotateCcwIcon aria-hidden="true" />
                Try again
              </SubmitButton>
            </form>
          ) : null}
          {!busy ? (
            <form action={deleteExportAction.bind(null, goalId, item.id)}>
              <SubmitButton
                size="sm"
                variant="ghost"
                aria-label={`Delete ${label.title}: ${item.source_title}`}
              >
                <Trash2Icon aria-hidden="true" />
                Delete
              </SubmitButton>
            </form>
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}
