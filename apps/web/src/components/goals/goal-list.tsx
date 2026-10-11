import Link from "next/link";

import { GoalCard } from "@/components/goals/goal-card";
import { Button } from "@/components/ui/button";
import type { Goal } from "@/lib/api/server";

type GoalListProps = {
  /** An accessible name for the list (a visible heading usually sits above it). */
  label: string;
  goals: readonly Goal[];
  /** Link to the next page of this list, if there is one. */
  nextHref?: string | undefined;
  /** Link back to the first page, shown while viewing a later page. */
  firstHref?: string | undefined;
};

/** A responsive grid of goals with "newer / older" links for long lists. */
export function GoalList({ label, goals, nextHref, firstHref }: GoalListProps) {
  return (
    <div className="space-y-6">
      <ul aria-label={label} className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {goals.map((goal) => (
          <li key={goal.id}>
            <GoalCard goal={goal} />
          </li>
        ))}
      </ul>
      {nextHref || firstHref ? (
        <nav aria-label={`${label} pages`} className="flex flex-wrap justify-center gap-3">
          {firstHref ? (
            <Button asChild variant="outline">
              <Link href={firstHref}>Back to newest</Link>
            </Button>
          ) : null}
          {nextHref ? (
            <Button asChild variant="outline">
              <Link href={nextHref}>Show older</Link>
            </Button>
          ) : null}
        </nav>
      ) : null}
    </div>
  );
}
