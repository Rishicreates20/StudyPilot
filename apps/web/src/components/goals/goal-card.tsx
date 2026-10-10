import { CalendarIcon, ClockIcon, LanguagesIcon } from "lucide-react";

import { Badge, type BadgeVariant } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { Goal } from "@/lib/api/server";
import { goalLevelLabel, goalTypeLabel, languageLabel } from "@/lib/goals/options";

const STATUS_BADGES: Record<Goal["status"], { label: string; variant: BadgeVariant }> = {
  active: { label: "Active", variant: "info" },
  paused: { label: "Paused", variant: "warning" },
  completed: { label: "Completed", variant: "success" },
  archived: { label: "Archived", variant: "secondary" },
};

/** "2026-11-08" -> "8 Nov 2026". Date-only values are formatted in UTC so no timezone shifts them. */
export function formatDate(isoDate: string): string {
  return new Intl.DateTimeFormat("en-GB", { dateStyle: "medium", timeZone: "UTC" }).format(
    new Date(`${isoDate}T00:00:00Z`),
  );
}

export function GoalCard({ goal }: { goal: Goal }) {
  const status = STATUS_BADGES[goal.status];

  return (
    <Card className="h-full">
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <CardTitle className="text-lg">{goal.title}</CardTitle>
          <Badge variant={status.variant}>{status.label}</Badge>
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
