import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import type { Goal } from "@/lib/api/server";
import { describeDaysAway, formatDate, formatMoment } from "@/lib/format";
import {
  goalLevelLabel,
  goalTypeLabel,
  languageLabel,
  learningPreferenceLabel,
} from "@/lib/goals/options";

type GoalDetailsProps = {
  goal: Goal;
  /** The learner's IANA timezone, for the moments shown (created, completed...). */
  timeZone: string;
  /** Days from today to the target date (negative once it has passed); null if there is none. */
  daysToTarget: number | null;
};

/** Everything the learner told us about a goal, and when it changed. */
export function GoalDetails({ goal, timeZone, daysToTarget }: GoalDetailsProps) {
  const overdue = daysToTarget !== null && daysToTarget < 0 && goal.status !== "completed";

  return (
    <Card>
      <CardContent className="space-y-8">
        {goal.description ? (
          <section aria-labelledby="goal-notes">
            <h2 id="goal-notes" className="text-sm font-medium text-muted-foreground">
              Notes
            </h2>
            <p className="mt-2 text-base whitespace-pre-line">{goal.description}</p>
          </section>
        ) : null}

        <dl className="grid gap-x-8 gap-y-6 sm:grid-cols-2">
          <Detail label="Kind of goal">{goalTypeLabel(goal.goal_type)}</Detail>
          <Detail label="Your level when you started">{goalLevelLabel(goal.current_level)}</Detail>
          <Detail label="Daily study time">{goal.daily_minutes} minutes</Detail>
          <Detail label="Target date">
            {goal.target_date ? (
              <>
                {formatDate(goal.target_date)}
                {daysToTarget !== null ? (
                  <span className={overdue ? "text-warning-foreground" : "text-muted-foreground"}>
                    {" "}
                    ({overdue ? "passed " : ""}
                    {describeDaysAway(daysToTarget)})
                  </span>
                ) : null}
              </>
            ) : (
              <span className="text-muted-foreground">No deadline</span>
            )}
          </Detail>
          <Detail label="Languages">
            {goal.preferred_languages.map(languageLabel).join(", ")}
          </Detail>
          <Detail label="How you like to learn">
            {goal.learning_preferences.length > 0 ? (
              <span className="flex flex-wrap gap-2">
                {goal.learning_preferences.map((preference) => (
                  <Badge key={preference} variant="secondary">
                    {learningPreferenceLabel(preference)}
                  </Badge>
                ))}
              </span>
            ) : (
              <span className="text-muted-foreground">No extras selected</span>
            )}
          </Detail>
        </dl>

        <dl className="grid gap-x-8 gap-y-2 border-t pt-6 text-sm text-muted-foreground sm:grid-cols-2">
          <Meta label="Created">{formatMoment(goal.created_at, timeZone)}</Meta>
          <Meta label="Last changed">{formatMoment(goal.updated_at, timeZone)}</Meta>
          {goal.completed_at ? (
            <Meta label="Completed">{formatMoment(goal.completed_at, timeZone)}</Meta>
          ) : null}
          {goal.archived_at ? (
            <Meta label="Archived">{formatMoment(goal.archived_at, timeZone)}</Meta>
          ) : null}
        </dl>
      </CardContent>
    </Card>
  );
}

function Detail({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-sm font-medium text-muted-foreground">{label}</dt>
      <dd className="mt-1 text-base">{children}</dd>
    </div>
  );
}

function Meta({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-2">
      <dt>{label}:</dt>
      <dd className="text-foreground">{children}</dd>
    </div>
  );
}
