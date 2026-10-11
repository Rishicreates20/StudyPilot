"use client";

import { JobProgress, POLL_INTERVAL_MS, SLOW_START_MS } from "@/components/jobs/job-progress";
import type { GenerationJob } from "@/lib/api/server";
import { cancelGenerationAction } from "@/lib/roadmaps/actions";
import { describeStage } from "@/lib/roadmaps/labels";

export { POLL_INTERVAL_MS, SLOW_START_MS };

type GenerationStatusProps = {
  goalId: string;
  job: Pick<
    GenerationJob,
    | "id"
    | "status"
    | "stage"
    | "progress"
    | "attempts"
    | "max_attempts"
    | "created_at"
    | "cancel_requested"
  >;
};

/** A roadmap being made: live progress, and a way to stop it. */
export function GenerationStatus({ goalId, job }: GenerationStatusProps) {
  return (
    <JobProgress
      job={job}
      title="Making your roadmap"
      description="This usually takes under a minute. You can leave this page; the roadmap will be here when you come back."
      stageText={describeStage(job)}
      cancelAction={cancelGenerationAction.bind(null, goalId, job.id)}
    />
  );
}
