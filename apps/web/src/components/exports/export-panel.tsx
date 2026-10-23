import { DownloadIcon, FolderDownIcon, InfoIcon } from "lucide-react";
import Link from "next/link";

import { SubmitButton } from "@/components/forms/submit-button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { requestLessonExportAction, requestRoadmapExportAction } from "@/lib/exports/actions";
import { FORMAT_LABELS, LESSON_FORMATS, ROADMAP_FORMATS } from "@/lib/exports/labels";
import { exportsPath } from "@/lib/exports/paths";

type ExportPanelProps = {
  goalId: string;
  kind: "lesson" | "roadmap";
  /** The lesson version or roadmap version being viewed: that is the one exported. */
  sourceId: string;
  /** Where to come back to if the request is refused (this page). */
  returnTo: string;
  /** An archived goal is read-only: nothing new can be exported. */
  readOnly?: boolean;
};

/**
 * "Download a copy": one native form with a button per format. The clicked button's value is the
 * format; the Server Action checks it against the known formats, asks the API, and takes the
 * learner to the goal's exported files, where the new file appears as soon as it is made.
 */
export function ExportPanel({ goalId, kind, sourceId, returnTo, readOnly }: ExportPanelProps) {
  const formats = kind === "lesson" ? LESSON_FORMATS : ROADMAP_FORMATS;
  const action =
    kind === "lesson"
      ? requestLessonExportAction.bind(null, goalId, sourceId, returnTo)
      : requestRoadmapExportAction.bind(null, goalId, sourceId, returnTo);
  const headingId = `export-${kind}-heading`;

  return (
    <Card aria-labelledby={headingId}>
      <CardHeader>
        <CardTitle id={headingId} className="flex items-center gap-2">
          <DownloadIcon className="size-4 text-primary" aria-hidden="true" />
          Download a copy
        </CardTitle>
        <CardDescription>
          {kind === "lesson"
            ? "Save this version of the lesson as a file to print, read offline or present."
            : "Save this version of the roadmap as a file to print or share."}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {readOnly ? (
          <p className="flex items-start gap-2 text-sm text-muted-foreground">
            <InfoIcon className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
            This goal is archived. Restore it to make new files; files made earlier are still in
            your exported files.
          </p>
        ) : (
          <form action={action} className="grid gap-3 sm:grid-cols-2">
            {formats.map((format) => (
              <SubmitButton
                key={format}
                name="format"
                value={format}
                variant="outline"
                className="h-auto flex-col items-start gap-1 py-3 text-left whitespace-normal"
              >
                <span className="font-semibold">{FORMAT_LABELS[format].title}</span>
                <span className="text-xs font-normal text-muted-foreground">
                  {FORMAT_LABELS[format].detail}
                </span>
              </SubmitButton>
            ))}
          </form>
        )}
        <Link
          href={exportsPath(goalId)}
          className="inline-flex items-center gap-1.5 rounded-sm text-sm text-primary underline-offset-4 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
        >
          <FolderDownIcon className="size-4" aria-hidden="true" />
          Your exported files
        </Link>
      </CardContent>
    </Card>
  );
}
