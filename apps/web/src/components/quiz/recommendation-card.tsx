import { ArrowRightIcon, CircleCheckIcon, CompassIcon } from "lucide-react";
import Link from "next/link";

import { SubmitButton } from "@/components/forms/submit-button";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { Recommendation } from "@/lib/api/server";
import { studyPath } from "@/lib/lessons/paths";
import { startQuizAction } from "@/lib/quizzes/actions";
import { recommendationTarget } from "@/lib/quizzes/state";

type RecommendationCardProps = {
  goalId: string;
  recommendation: Recommendation;
  /** The goal is archived: say what the next step would be, but offer no button. */
  readOnly?: boolean;
  /** A smaller card for lists (the dashboard). */
  compact?: boolean;
};

/**
 * The one recommended next step: what to do, why (the reason names the evidence, such as a score),
 * the parts of the topic it is about, and a button that does it.
 */
export function RecommendationCard({
  goalId,
  recommendation,
  readOnly = false,
  compact = false,
}: RecommendationCardProps) {
  const target = readOnly
    ? { kind: "none" as const }
    : recommendationTarget(goalId, recommendation);
  const done = recommendation.action === "all_done";
  const Icon = done ? CircleCheckIcon : CompassIcon;

  return (
    <Card className="border-primary/30 bg-primary/5">
      <CardHeader className={compact ? "pb-2" : undefined}>
        <CardTitle className="flex items-center gap-2 text-base">
          <Icon className="size-5 text-primary" aria-hidden="true" />
          {done ? "You're up to date" : "Your next step"}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm">{recommendation.reason}</p>
        {!compact && recommendation.objective_texts.length > 0 ? (
          <div className="space-y-1.5 text-sm">
            <p className="font-medium">The parts to work on</p>
            <ul className="list-disc space-y-1 pl-5 text-muted-foreground">
              {recommendation.objective_texts.map((text) => (
                <li key={text}>{text}</li>
              ))}
            </ul>
          </div>
        ) : null}
        {target.kind === "link" ? (
          <Button asChild>
            <Link href={target.href}>
              {target.label}
              <ArrowRightIcon aria-hidden="true" />
            </Link>
          </Button>
        ) : null}
        {target.kind === "start-quiz" ? (
          <form action={startQuizAction.bind(null, goalId, target.itemId, target.purpose)}>
            <SubmitButton>
              {target.label}
              <ArrowRightIcon aria-hidden="true" />
            </SubmitButton>
          </form>
        ) : null}
        {recommendation.review_lesson && recommendation.item_id && !readOnly ? (
          <p className="text-sm text-muted-foreground">
            Start by going over{" "}
            <Link
              href={studyPath(goalId, recommendation.item_id)}
              className="font-medium text-primary underline-offset-4 hover:underline"
            >
              {recommendation.item_title ? `“${recommendation.item_title}”` : "the lesson"}
            </Link>{" "}
            again. You don&rsquo;t need to repeat the rest of the course.
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}
