"use client";

import { LoaderCircleIcon } from "lucide-react";
import { useEffect, useState } from "react";

import { POLL_INTERVAL_MS, useServerRefresh } from "@/components/jobs/use-server-refresh";
import { SubmitButton } from "@/components/forms/submit-button";
import { ProgressBar } from "@/components/progress/progress-bar";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { GenerationJob } from "@/lib/api/server";

export { POLL_INTERVAL_MS };
/** After this long still waiting for a worker to pick the job up, say so. */
export const SLOW_START_MS = 45_000;

type JobProgressProps = {
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
  title: string;
  description: string;
  /** What the job is doing now, in words ("Planning your roadmap…"). */
  stageText: string;
  /** A form action that asks the job to stop, already bound to its goal / topic and job. */
  cancelAction: (formData: FormData) => void | Promise<void>;
};

/**
 * A background job in progress. While it is on screen it re-renders the page from the server every
 * couple of seconds (`router.refresh()`), so the token stays on the server and nothing but the
 * job's learner-safe status ever reaches the browser. When the job finishes, the server renders
 * the result (or the failure) in its place and this component simply goes away.
 */
export function JobProgress({
  job,
  title,
  description,
  stageText,
  cancelAction,
}: JobProgressProps) {
  useServerRefresh();
  const [slowStart, setSlowStart] = useState(false);

  useEffect(() => {
    const created = Date.parse(job.created_at);
    const check = () =>
      setSlowStart(
        job.status === "queued" && job.attempts === 0 && Date.now() - created > SLOW_START_MS,
      );
    check();
    const timer = setInterval(check, 5_000);
    return () => clearInterval(timer);
  }, [job.created_at, job.status, job.attempts]);

  // `attempts` counts the tries already started: a queued job is waiting for its next one, a
  // running job is on its latest. Anything past the first is a retry, and the learner is told so
  // (a long wait with no explanation looks like a crash).
  const attemptNumber = job.status === "queued" ? job.attempts + 1 : job.attempts;
  const retrying = attemptNumber > 1;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-lg">
          <LoaderCircleIcon
            className="size-5 animate-spin text-primary motion-reduce:animate-none"
            aria-hidden="true"
          />
          {title}
        </CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <ProgressBar label={stageText} value={job.progress} />
        {/* Announced politely to screen readers whenever the stage changes. */}
        <p className="sr-only" role="status" aria-live="polite">
          {stageText} {job.progress}%
        </p>
        {retrying ? (
          <>
            <p className="text-sm text-muted-foreground">
              Attempt {Math.min(attemptNumber, job.max_attempts)} of {job.max_attempts}.
            </p>
            <p className="text-sm text-muted-foreground">
              The first try did not work out (often the AI service is busy), so it is being tried
              again. Nothing is wrong with your account.
            </p>
          </>
        ) : null}
        {slowStart ? (
          <p className="text-sm text-muted-foreground">
            This is taking longer than usual. Your request is saved and will start as soon as a
            worker is free.
          </p>
        ) : null}
        <div className="flex items-center gap-3">
          {job.cancel_requested ? (
            <span className="text-sm text-muted-foreground">Stopping…</span>
          ) : (
            <form action={cancelAction}>
              <SubmitButton variant="outline" size="sm">
                Cancel
              </SubmitButton>
            </form>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
