"use client";

import { LoaderCircleIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { SubmitButton } from "@/components/forms/submit-button";
import { ProgressBar } from "@/components/progress/progress-bar";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { GenerationJob } from "@/lib/api/server";
import { describeStage } from "@/lib/roadmaps/labels";
import { cancelGenerationAction } from "@/lib/roadmaps/actions";

/** How often the page asks the server for the job's current state. */
export const POLL_INTERVAL_MS = 2_000;
/** After this long still waiting for a worker to pick the job up, say so. */
export const SLOW_START_MS = 45_000;

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

/**
 * A roadmap being made. While it is on screen it re-renders the page from the server every couple
 * of seconds (`router.refresh()`), so the token stays on the server and nothing but the job's
 * learner-safe status ever reaches the browser. When the job finishes, the server renders the
 * finished roadmap (or the failure) in its place and this component simply goes away.
 */
export function GenerationStatus({ goalId, job }: GenerationStatusProps) {
  const router = useRouter();
  const [slowStart, setSlowStart] = useState(false);

  useEffect(() => {
    const timer = setInterval(() => router.refresh(), POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [router]);

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

  const stage = describeStage(job);
  const retrying = job.status === "queued" && job.attempts > 0;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-lg">
          <LoaderCircleIcon
            className="size-5 animate-spin text-primary motion-reduce:animate-none"
            aria-hidden="true"
          />
          Making your roadmap
        </CardTitle>
        <CardDescription>
          This usually takes under a minute. You can leave this page; the roadmap will be here when
          you come back.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <ProgressBar label={stage} value={job.progress} />
        {/* Announced politely to screen readers whenever the stage changes. */}
        <p className="sr-only" role="status" aria-live="polite">
          {stage} {job.progress}%
        </p>
        {retrying ? (
          <p className="text-sm text-muted-foreground">
            Attempt {Math.min(job.attempts + 1, job.max_attempts)} of {job.max_attempts}.
          </p>
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
            <form action={cancelGenerationAction.bind(null, goalId, job.id)}>
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
