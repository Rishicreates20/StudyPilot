import { CalendarIcon, ClockIcon, LanguagesIcon } from "lucide-react";
import Link from "next/link";

import { GoalStatusBadge } from "@/components/goals/goal-status-badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { Goal } from "@/lib/api/server";
import { formatDate } from "@/lib/format";
import { goalPath } from "@/lib/goals/ids";
import { goalLevelLabel, goalTypeLabel, languageLabel } from "@/lib/goals/options";

export { formatDate };

/** A goal in a list. The title is the link to the goal's page. */
export function GoalCard({ goal }: { goal: Goal }) {
  return (
    <Card className="relative h-full transition-colors hover:border-primary/40">
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <CardTitle className="text-lg">
            {/* The link's ::after covers the whole card, so the card is one big tap target. */}
            <Link
              href={goalPath(goal.id)}
              className="rounded-sm outline-none after:absolute after:inset-0 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
            >
              {goal.title}
            </Link>
          </CardTitle>
          <GoalStatusBadge status={goal.status} />
        </div>
        <CardDescription>
          {goalTypeLabel(goal.goal_type)} · Level: {goalLevelLabel(goal.current_level)}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {goal.description ? (
          <p className="line-clamp-3 text-sm text-muted-foreground">{goal.description}</p>
        ) : null}
        <dl className="grid gap-2 text-sm">
          <div className="flex items-center gap-2">
            <ClockIcon className="size-4 text-muted-foreground" aria-hidden="true" />
            <dt className="sr-only">Daily study time</dt>
            <dd>{goal.daily_minutes} minutes a day</dd>
          </div>
          {goal.target_date ? (
            <div className="flex items-center gap-2">
              <CalendarIcon className="size-4 text-muted-foreground" aria-hidden="true" />
              <dt className="sr-only">Target date</dt>
              <dd>By {formatDate(goal.target_date)}</dd>
            </div>
          ) : null}
          <div className="flex items-center gap-2">
            <LanguagesIcon className="size-4 text-muted-foreground" aria-hidden="true" />
            <dt className="sr-only">Languages</dt>
            <dd>{goal.preferred_languages.map(languageLabel).join(", ")}</dd>
          </div>
        </dl>
      </CardContent>
    </Card>
  );
}
