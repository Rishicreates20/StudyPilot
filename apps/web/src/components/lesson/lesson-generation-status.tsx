"use client";

import { JobProgress } from "@/components/jobs/job-progress";
import type { GenerationJob } from "@/lib/api/server";
import { cancelLessonAction } from "@/lib/lessons/actions";
import { describeLessonStage } from "@/lib/lessons/labels";

type LessonGenerationStatusProps = {
  goalId: string;
  itemId: string;
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
  /** A lesson already exists: this job is writing another version of it. */
  newVersion?: boolean;
};

/** A lesson being written: live progress, and a way to stop it. */
export function LessonGenerationStatus({
  goalId,
  itemId,
  job,
  newVersion = false,
}: LessonGenerationStatusProps) {
  return (
    <JobProgress
      job={job}
      title={newVersion ? "Writing a new version of this lesson" : "Writing your lesson"}
      description={
        newVersion
          ? "The lesson below stays available while the new version is written. It usually takes under a minute."
          : "This usually takes under a minute. You can leave this page; the lesson will be here when you come back."
      }
      stageText={describeLessonStage(job)}
      cancelAction={cancelLessonAction.bind(null, goalId, itemId, job.id)}
    />
  );
}
