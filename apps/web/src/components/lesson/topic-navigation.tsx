import { ArrowLeftIcon, ArrowRightIcon } from "lucide-react";
import Link from "next/link";

import type { NeighbourTopic } from "@/lib/api/server";
import { studyPath } from "@/lib/lessons/paths";
import { roadmapPath } from "@/lib/roadmaps/paths";

const CARD =
  "group flex flex-col gap-1 rounded-lg border bg-card p-4 outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring";

type TopicNavigationProps = {
  goalId: string;
  previous: NeighbourTopic | null;
  next: NeighbourTopic | null;
};

/** Previous and next topic of the roadmap; after the last topic, a way back to the roadmap. */
export function TopicNavigation({ goalId, previous, next }: TopicNavigationProps) {
  return (
    <nav aria-label="Topic navigation" className="grid gap-3 sm:grid-cols-2">
      {previous ? (
        <Link href={studyPath(goalId, previous.id)} className={CARD}>
          <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <ArrowLeftIcon className="size-3.5" aria-hidden="true" />
            Previous topic
          </span>
          <span className="font-medium">{previous.title}</span>
        </Link>
      ) : (
        <span aria-hidden="true" className="hidden sm:block" />
      )}
      {next ? (
        <Link href={studyPath(goalId, next.id)} className={`${CARD} sm:items-end sm:text-right`}>
          <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
            Next topic
            <ArrowRightIcon className="size-3.5" aria-hidden="true" />
          </span>
          <span className="font-medium">{next.title}</span>
        </Link>
      ) : (
        <Link href={roadmapPath(goalId)} className={`${CARD} sm:items-end sm:text-right`}>
          <span className="text-xs text-muted-foreground">That was the last topic</span>
          <span className="font-medium">Back to the roadmap</span>
        </Link>
      )}
    </nav>
  );
}
