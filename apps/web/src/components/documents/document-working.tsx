"use client";

import { JobProgress } from "@/components/jobs/job-progress";
import type { GenerationJob } from "@/lib/api/server";
import { cancelDocumentJobAction } from "@/lib/documents/actions";
import { describeDocumentStage } from "@/lib/documents/labels";

/** A document being read and indexed: live progress, and a way to stop it. */
export function DocumentWorking({
  goalId,
  documentId,
  job,
}: {
  goalId: string;
  documentId: string;
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
}) {
  return (
    <JobProgress
      job={job}
      title="Reading your document"
      description="Its text is taken out, split into passages and indexed so it can be searched and cited. You can leave this page; the document will be ready when you come back."
      stageText={describeDocumentStage(job)}
      cancelAction={cancelDocumentJobAction.bind(null, goalId, documentId, job.id)}
    />
  );
}
