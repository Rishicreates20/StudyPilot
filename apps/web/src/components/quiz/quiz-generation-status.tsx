"use client";

import { JobProgress } from "@/components/jobs/job-progress";
import type { GenerationJob } from "@/lib/api/server";
import { cancelMarkingAction, cancelQuizAction } from "@/lib/quizzes/actions";
import { describeGradingStage, describeQuizStage } from "@/lib/quizzes/labels";

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

/** A quiz being written: live progress, and a way to stop it. */
export function QuizGenerationStatus({
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
      title="Writing your quiz"
      description="The questions come from your lesson. This usually takes under a minute, and you can leave this page: the quiz will be here when you come back."
      stageText={describeQuizStage(job)}
      cancelAction={cancelQuizAction.bind(null, goalId, itemId, job.id)}
    />
  );
}

/** Short answers being marked against their rubric. */
export function GradingStatus({
  goalId,
  itemId,
  attemptId,
  job,
}: {
  goalId: string;
  itemId: string;
  attemptId: string;
  job: JobSummary;
}) {
  return (
    <JobProgress
      job={job}
      title="Marking your short answers"
      description="Your multiple-choice and true/false answers are already marked. The short answers are compared with their rubric in the background; this page updates by itself."
      stageText={describeGradingStage(job)}
      cancelAction={cancelMarkingAction.bind(null, goalId, itemId, attemptId, job.id)}
    />
  );
}
