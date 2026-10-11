import Link from "next/link";

import { SubmitButton } from "@/components/forms/submit-button";
import { Badge } from "@/components/ui/badge";
import type { RoadmapSummary } from "@/lib/api/server";
import { formatMoment } from "@/lib/format";
import { makeRoadmapCurrentAction } from "@/lib/roadmaps/actions";
import { formatMinutes, pluralize } from "@/lib/roadmaps/labels";
import { roadmapPath } from "@/lib/roadmaps/paths";

type VersionHistoryProps = {
  goalId: string;
  versions: readonly RoadmapSummary[];
  /** The version being looked at. */
  viewingId: string;
  /** Archived goals are read-only, so versions can't be switched. */
  archived: boolean;
  timeZone: string;
};

/**
 * Every version of the roadmap, newest first. Nothing is ever removed: making another version
 * current only changes which one the goal shows by default.
 */
export function VersionHistory({
  goalId,
  versions,
  viewingId,
  archived,
  timeZone,
}: VersionHistoryProps) {
  return (
    <section aria-labelledby="versions-heading" className="space-y-3">
      <h2 id="versions-heading" className="font-heading text-xl font-semibold tracking-tight">
        Versions
      </h2>
      <p className="text-sm text-muted-foreground">
        Each time you revise or regenerate, a new version is added. Earlier versions are kept, and
        you can switch back at any time.
      </p>
      <ul className="divide-y rounded-lg border bg-card">
        {versions.map((version) => {
          const viewing = version.id === viewingId;
          return (
            <li
              key={version.id}
              className="flex flex-wrap items-center justify-between gap-3 px-4 py-3"
            >
              <div className="min-w-0 space-y-1">
                <p className="flex flex-wrap items-center gap-2 text-sm font-medium">
                  {viewing ? (
                    <span aria-current="page">Version {version.version} (viewing)</span>
                  ) : (
                    <Link
                      href={roadmapPath(goalId, version.version)}
                      className="rounded-sm underline underline-offset-4 outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      Version {version.version}
                    </Link>
                  )}
                  {version.status === "current" ? <Badge variant="info">Current</Badge> : null}
                  {version.is_synthetic ? <Badge variant="warning">Sample plan</Badge> : null}
                </p>
                <p className="text-xs text-muted-foreground">
                  {formatMoment(version.created_at, timeZone)} ·{" "}
                  {pluralize(version.topic_count, "topic")} · {formatMinutes(version.total_minutes)}
                  {version.revision_feedback ? ` · Asked for: “${version.revision_feedback}”` : ""}
                </p>
              </div>
              {version.status !== "current" && !archived ? (
                <form action={makeRoadmapCurrentAction.bind(null, goalId, version.id)}>
                  <SubmitButton variant="outline" size="sm">
                    Make current
                  </SubmitButton>
                </form>
              ) : null}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
