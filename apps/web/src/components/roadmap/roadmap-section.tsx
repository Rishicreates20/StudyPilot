import { redirect } from "next/navigation";
import { connection } from "next/server";

import { LoadError } from "@/components/feedback/load-error";
import { RoadmapPanel } from "@/components/roadmap/roadmap-panel";
import { Skeleton } from "@/components/ui/skeleton";
import {
  ApiError,
  fetchGoalJobs,
  fetchRoadmaps,
  type GoalStatus,
  type JobList,
  type RoadmapList,
} from "@/lib/api/server";
import { sessionEndedUrlFor } from "@/lib/auth/paths";
import { requireApiSession } from "@/lib/auth/session";
import { goalPath } from "@/lib/goals/ids";
import { roadmapPanelState } from "@/lib/roadmaps/state";

const RECENT_JOBS = 3;

export function RoadmapSectionSkeleton() {
  return (
    <div className="space-y-4" role="status" aria-label="Loading the roadmap">
      <Skeleton className="h-7 w-28" />
      <Skeleton className="h-48 w-full" />
    </div>
  );
}

type RoadmapSectionProps = {
  goalId: string;
  goalStatus: GoalStatus;
  timeZone: string;
};

/**
 * The goal page's roadmap section, loaded on its own so the goal itself appears first. It reads
 * the goal's roadmap versions and recent jobs from the API as the signed-in user and hands the
 * result to the presentational panel. While a job is running, the panel's status card refreshes
 * this component every couple of seconds.
 */
export async function RoadmapSection({ goalId, goalStatus, timeZone }: RoadmapSectionProps) {
  await connection(); // job state changes under us: never reuse a rendered answer
  const { accessToken } = await requireApiSession(goalPath(goalId));

  let versions: RoadmapList;
  let jobs: JobList;
  try {
    [versions, jobs] = await Promise.all([
      fetchRoadmaps(accessToken, goalId),
      fetchGoalJobs(accessToken, goalId, RECENT_JOBS),
    ]);
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    if (error.isUnauthenticated) redirect(sessionEndedUrlFor(goalPath(goalId)));
    return (
      <LoadError
        title="We couldn't load the roadmap"
        description={
          error.status === 0 || error.status === 503
            ? "The learning service is temporarily unavailable. Your goal and any roadmap are safe."
            : "Something went wrong while loading the roadmap."
        }
        retryHref={goalPath(goalId)}
        reference={error.requestId}
      />
    );
  }

  return (
    <RoadmapPanel
      goalId={goalId}
      goalStatus={goalStatus}
      timeZone={timeZone}
      state={roadmapPanelState(jobs.items, versions.items)}
    />
  );
}
