"use client";

import { JobProgress } from "@/components/jobs/job-progress";
import type { GenerationJob } from "@/lib/api/server";
import { cancelVideoSearchAction } from "@/lib/videos/actions";
import { describeVideoStage } from "@/lib/videos/labels";

type JobSummary = Pick<
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

/** A video search in progress: live progress, and a way to stop it. */
export function VideoSearchStatus({
  goalId,
  itemId,
  job,
}: {
  goalId: string;
  itemId: string;
  job: JobSummary;
}) {
  return (
    <JobProgress
      job={job}
      title="Finding videos on YouTube"
      description="Videos are checked for length, language and availability before they are suggested. This usually takes a few seconds, and you can leave this page."
      stageText={describeVideoStage(job)}
      cancelAction={cancelVideoSearchAction.bind(null, goalId, itemId, job.id)}
    />
  );
}
