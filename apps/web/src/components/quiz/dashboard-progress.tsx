import { TrendingUpIcon } from "lucide-react";
import Link from "next/link";
import { connection } from "next/server";

import { ProgressCounts } from "@/components/quiz/progress-section";
import { RecommendationCard } from "@/components/quiz/recommendation-card";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { fetchGoalProgress, type GoalProgress, type GoalPage } from "@/lib/api/server";
import { DASHBOARD_PATH } from "@/lib/auth/paths";
import { requireApiSession } from "@/lib/auth/session";
import { goalPath } from "@/lib/goals/ids";
import { bandLabel } from "@/lib/quizzes/labels";
import { weakTopics } from "@/lib/quizzes/state";

/** How many active goals get a progress card on the dashboard. */
const MAX_GOALS = 3;

type Entry = { goal: GoalPage["items"][number]; progress: GoalProgress };

/**
 * "Where you stand": for each active goal that has a roadmap, how many topics are mastered, getting
 * there or need practice, which topics are weakest, and the recommended next step. Each goal is
 * read on its own and a goal whose progress can't be read is simply left out, so one failure never
 * hides the rest of the dashboard. Renders nothing when no goal has a roadmap yet.
 */
export async function DashboardProgress({ goals }: { goals: GoalPage["items"] }) {
  await connection(); // results change under us: never reuse a rendered answer
  const { accessToken } = await requireApiSession(DASHBOARD_PATH);

  const active = goals.filter((goal) => goal.status === "active").slice(0, MAX_GOALS);
  const loaded = await Promise.all(
    active.map(async (goal): Promise<Entry | null> => {
      try {
        const progress = await fetchGoalProgress(accessToken, goal.id);
        return progress.topics.some((topic) => topic.kind !== "revision")
          ? { goal, progress }
          : null;
      } catch {
        return null;
      }
    }),
  );
  const entries = loaded.filter((entry): entry is Entry => entry !== null);
  if (entries.length === 0) return null;

  return (
    <section aria-labelledby="progress-heading" className="space-y-6">
      <h2 id="progress-heading" className="text-xl font-semibold tracking-tight">
        Where you stand
      </h2>
      <div className="grid gap-4 lg:grid-cols-2">
        {entries.map(({ goal, progress }) => {
          const weak = weakTopics(progress).slice(0, 3);
          return (
            <Card key={goal.id}>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base">
                  <TrendingUpIcon className="size-5 text-primary" aria-hidden="true" />
                  <Link href={goalPath(goal.id)} className="underline-offset-4 hover:underline">
                    {goal.title}
                  </Link>
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <ProgressCounts counts={progress.counts} />
                {weak.length > 0 ? (
                  <div className="space-y-1.5 text-sm">
                    <p className="font-medium">Weakest topics</p>
                    <ul className="space-y-1">
                      {weak.map((topic) => (
                        <li key={topic.item_id}>
                          <Link
                            href={`${goalPath(goal.id)}/learn/${topic.item_id}`}
                            className="underline-offset-4 hover:underline"
                          >
                            {topic.title}
                          </Link>{" "}
                          <span className="text-muted-foreground">
                            · {bandLabel("needs_practice")}
                            {topic.mastery ? `, ${Math.round(topic.mastery.score)}%` : ""}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
                {progress.recommendation ? (
                  <RecommendationCard
                    goalId={goal.id}
                    recommendation={progress.recommendation}
                    compact
                  />
                ) : null}
              </CardContent>
            </Card>
          );
        })}
      </div>
    </section>
  );
}
