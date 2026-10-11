import {
  ArrowRightIcon,
  CircleAlertIcon,
  PencilIcon,
  RotateCcwIcon,
  SparklesIcon,
} from "lucide-react";
import Link from "next/link";

import { EmptyState } from "@/components/feedback/empty-state";
import { SubmitButton } from "@/components/forms/submit-button";
import { ProgressBar } from "@/components/progress/progress-bar";
import { GenerationStatus } from "@/components/roadmap/generation-status";
import { RegenerateDialog } from "@/components/roadmap/regenerate-dialog";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { GoalStatus } from "@/lib/api/server";
import { formatMoment } from "@/lib/format";
import { editGoalPath } from "@/lib/goals/ids";
import { formatMinutes, pluralize } from "@/lib/roadmaps/labels";
import { generateRoadmapAction, retryGenerationAction } from "@/lib/roadmaps/actions";
import { roadmapPath } from "@/lib/roadmaps/paths";
import type { RoadmapPanelState } from "@/lib/roadmaps/state";

type RoadmapPanelProps = {
  goalId: string;
  goalStatus: GoalStatus;
  state: RoadmapPanelState;
  timeZone: string;
};

/**
 * The roadmap section of a goal: an invitation to make one, its progress while it is being made,
 * a clear failure with a way forward, or the finished plan. Which one is decided by
 * `roadmapPanelState`; this component only presents it.
 */
export function RoadmapPanel({ goalId, goalStatus, state, timeZone }: RoadmapPanelProps) {
  const archived = goalStatus === "archived";

  return (
    <section aria-labelledby="roadmap-heading" className="space-y-4">
      <h2 id="roadmap-heading" className="font-heading text-xl font-semibold tracking-tight">
        Roadmap
      </h2>

      {state.kind === "generating" ? <GenerationStatus goalId={goalId} job={state.job} /> : null}

      {state.kind === "failed" ? (
        <div className="space-y-3">
          <Alert variant="destructive">
            <CircleAlertIcon aria-hidden="true" />
            <AlertTitle>We couldn&rsquo;t make your roadmap</AlertTitle>
            <AlertDescription>
              <p>{state.job.error_message ?? "Something went wrong. Please try again."}</p>
            </AlertDescription>
          </Alert>
          <div className="flex flex-wrap gap-2">
            {archived ? null : (
              <form action={retryGenerationAction.bind(null, goalId, state.job.id)}>
                <SubmitButton>
                  <RotateCcwIcon aria-hidden="true" />
                  Try again
                </SubmitButton>
              </form>
            )}
            {archived ? null : (
              <Button asChild variant="outline">
                <Link href={editGoalPath(goalId)}>
                  <PencilIcon aria-hidden="true" />
                  Edit goal
                </Link>
              </Button>
            )}
            {state.current ? (
              <Button asChild variant="ghost">
                <Link href={roadmapPath(goalId)}>View your previous roadmap</Link>
              </Button>
            ) : null}
          </div>
        </div>
      ) : null}

      {state.kind === "ready" ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">{state.current.title}</CardTitle>
            <CardDescription>
              Version {state.current.version} of {state.versions}, made{" "}
              {formatMoment(state.current.created_at, timeZone)}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="info">Current</Badge>
              {state.current.is_synthetic ? <Badge variant="warning">Sample plan</Badge> : null}
            </div>
            <dl className="grid gap-4 text-sm sm:grid-cols-3">
              <div>
                <dt className="text-muted-foreground">Topics</dt>
                <dd className="text-lg font-semibold tabular-nums">{state.current.topic_count}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Study time</dt>
                <dd className="text-lg font-semibold tabular-nums">
                  {formatMinutes(state.current.total_minutes)}
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Duration</dt>
                <dd className="text-lg font-semibold tabular-nums">
                  {pluralize(state.current.total_days, "day")}
                </dd>
              </div>
            </dl>
            <ProgressBar
              label="Topics finished"
              value={state.current.completed_topics}
              max={state.current.topic_count}
              description={`${state.current.completed_topics} of ${state.current.topic_count} topics finished`}
            />
            <div className="flex flex-wrap gap-2">
              <Button asChild>
                <Link href={roadmapPath(goalId)}>
                  {!archived && state.current.completed_topics > 0
                    ? "Continue studying"
                    : "View roadmap"}
                  <ArrowRightIcon aria-hidden="true" />
                </Link>
              </Button>
              {archived ? null : <RegenerateDialog goalId={goalId} hasRoadmap />}
            </div>
          </CardContent>
        </Card>
      ) : null}

      {state.kind === "none" ? (
        <EmptyState
          icon={SparklesIcon}
          title="Turn this goal into a study plan"
          description={
            archived
              ? "Restore this goal to generate a roadmap for it."
              : "StudyPilot plans a step-by-step roadmap from your level, daily time and target date. It is made in the background, and you can revise or regenerate it later without losing earlier versions."
          }
          action={
            archived ? undefined : (
              <form action={generateRoadmapAction.bind(null, goalId)}>
                <SubmitButton>
                  <SparklesIcon aria-hidden="true" />
                  Generate roadmap
                </SubmitButton>
              </form>
            )
          }
        />
      ) : null}
    </section>
  );
}
