import { redirect } from "next/navigation";
import { connection } from "next/server";

import { LoadError } from "@/components/feedback/load-error";
import { RecommendationCard } from "@/components/quiz/recommendation-card";
import { TopicProgressList } from "@/components/quiz/topic-progress-list";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, fetchGoalProgress, type GoalProgress, type GoalStatus } from "@/lib/api/server";
import { sessionEndedUrlFor } from "@/lib/auth/paths";
import { requireApiSession } from "@/lib/auth/session";
import { goalPath } from "@/lib/goals/ids";

export function ProgressSectionSkeleton() {
  return (
    <div className="space-y-4" role="status" aria-label="Loading your progress">
      <Skeleton className="h-7 w-40" />
      <Skeleton className="h-32 w-full" />
    </div>
  );
}

/** The counts of a goal's topics by how well they are known, as a short definition list. */
export function ProgressCounts({ counts }: { counts: GoalProgress["counts"] }) {
  const items = [
    { label: "Mastered", value: counts.mastered },
    { label: "Getting there", value: counts.progressing },
    { label: "Needs practice", value: counts.needs_practice },
    { label: "Not assessed yet", value: counts.not_assessed },
  ];
  return (
    <dl className="grid grid-cols-2 gap-4 text-sm sm:grid-cols-4">
      {items.map((item) => (
        <div key={item.label}>
          <dt className="text-muted-foreground">{item.label}</dt>
          <dd className="text-lg font-semibold tabular-nums">{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}

type ProgressSectionProps = {
  goalId: string;
  goalStatus: GoalStatus;
};

/**
 * The goal page's progress section: how well each topic is known, which are weak, and the one
 * recommended next step. Loaded on its own so the goal and its roadmap appear first. A goal with no
 * roadmap yet has nothing to show, so it renders nothing.
 */
export async function ProgressSection({ goalId, goalStatus }: ProgressSectionProps) {
  await connection(); // results change under us: never reuse a rendered answer
  const { accessToken } = await requireApiSession(goalPath(goalId));

  let progress: GoalProgress;
  try {
    progress = await fetchGoalProgress(accessToken, goalId);
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    if (error.isUnauthenticated) redirect(sessionEndedUrlFor(goalPath(goalId)));
    return (
      <LoadError
        title="We couldn't load your progress"
        description="Your quizzes and results are safe. Please try again."
        retryHref={goalPath(goalId)}
        reference={error.requestId}
      />
    );
  }

  const topics = progress.topics.filter((topic) => topic.kind !== "revision");
  if (progress.roadmap_id === null || topics.length === 0) return null;

  return (
    <section aria-labelledby="progress-heading" className="space-y-5">
      <h2 id="progress-heading" className="font-heading text-xl font-semibold tracking-tight">
        Your mastery
      </h2>
      <ProgressCounts counts={progress.counts} />
      {progress.recommendation ? (
        <RecommendationCard
          goalId={goalId}
          recommendation={progress.recommendation}
          readOnly={goalStatus === "archived"}
        />
      ) : null}
      <TopicProgressList goalId={goalId} topics={topics} />
    </section>
  );
}
