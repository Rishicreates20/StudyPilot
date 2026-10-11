import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import type { LessonVersion } from "@/lib/api/server";
import { formatMoment } from "@/lib/format";
import { adjustLabel } from "@/lib/lessons/labels";
import { studyPath } from "@/lib/lessons/paths";

type LessonVersionsProps = {
  goalId: string;
  itemId: string;
  versions: readonly LessonVersion[];
  /** The version being read. */
  viewingId: string;
  timeZone: string;
};

/**
 * Every version of this topic's lesson, newest first. Nothing is ever removed: a new version only
 * changes which one a topic opens by default, and an earlier one can always be read again.
 */
export function LessonVersions({
  goalId,
  itemId,
  versions,
  viewingId,
  timeZone,
}: LessonVersionsProps) {
  if (versions.length < 2) return null;
  return (
    <section aria-labelledby="lesson-versions-heading" className="space-y-3">
      <h2
        id="lesson-versions-heading"
        className="font-heading text-xl font-semibold tracking-tight"
      >
        Versions of this lesson
      </h2>
      <ul className="divide-y rounded-lg border bg-card">
        {versions.map((version) => {
          const viewing = version.id === viewingId;
          const how = adjustLabel(version.adjust);
          return (
            <li key={version.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-3">
              <p className="flex flex-wrap items-center gap-2 text-sm font-medium">
                {viewing ? (
                  <span aria-current="page">Version {version.version} (reading)</span>
                ) : (
                  <Link
                    href={studyPath(goalId, itemId, version.id)}
                    className="rounded-sm underline underline-offset-4 outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    Version {version.version}
                  </Link>
                )}
                {version.status === "current" ? <Badge variant="info">Newest</Badge> : null}
                {how ? <Badge variant="outline">{how}</Badge> : null}
                {version.is_synthetic ? <Badge variant="warning">Sample lesson</Badge> : null}
              </p>
              <p className="text-xs text-muted-foreground">
                {formatMoment(version.created_at, timeZone)}
              </p>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
