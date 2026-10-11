import { CircleAlertIcon, RotateCcwIcon } from "lucide-react";

import { AnswerReview } from "@/components/quiz/answer-review";
import { MasteryMeter } from "@/components/quiz/mastery";
import { GradingStatus } from "@/components/quiz/quiz-generation-status";
import { RecommendationCard } from "@/components/quiz/recommendation-card";
import { SubmitButton } from "@/components/forms/submit-button";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { AttemptResult } from "@/lib/api/server";
import { formatMoment } from "@/lib/format";
import { regradeAction } from "@/lib/quizzes/actions";
import { formatPercent, formatPoints } from "@/lib/quizzes/labels";
import { weakObjectives } from "@/lib/quizzes/state";

const ACTIVE = new Set(["queued", "running"]);

type ResultsViewProps = {
  goalId: string;
  itemId: string;
  result: AttemptResult;
  timeZone: string;
  readOnly: boolean;
};

/**
 * The results of a submitted quiz, in the order a learner wants them: the score, whether marking is
 * still going on, how well the topic is now known and where it is weak, the recommended next step,
 * and then every question with its right answer and explanation.
 */
export function ResultsView({ goalId, itemId, result, timeZone, readOnly }: ResultsViewProps) {
  const graded = result.status === "graded";
  const job = result.grading_job;
  const marking = !graded && job !== null && ACTIVE.has(job.status);
  const markingFailed = !graded && !marking;
  const weak = weakObjectives(result);
  const mastery = result.mastery;

  return (
    <div className="space-y-8">
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Your score</CardTitle>
          <CardDescription>
            Submitted {formatMoment(result.submitted_at, timeZone)}
            {result.purpose === "practice" ? " · Practice quiz" : ""}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {graded && result.percent !== null ? (
            <p className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <span className="font-heading text-5xl font-semibold tabular-nums">
                {formatPercent(result.percent)}
              </span>
              <span className="text-muted-foreground">
                {formatPoints(result.points_earned ?? 0)} of {result.points_possible} points
              </span>
            </p>
          ) : (
            <p className="text-sm text-muted-foreground">
              Your score appears once your{" "}
              {result.pending_answers === 1 ? "short answer is" : "short answers are"} marked.
              Everything you answered by choosing an option is already marked below.
            </p>
          )}
          <div className="flex flex-wrap gap-2">
            {result.is_synthetic ? (
              <Badge variant="warning">Sample quiz (not written by an AI)</Badge>
            ) : null}
            {result.answers.some((answer) => answer.grading_method === "ai_estimate") ? (
              <Badge variant="warning">Includes an AI estimate</Badge>
            ) : null}
            {result.answers.some((answer) => answer.grading_method === "self_review") ? (
              <Badge variant="secondary">Includes your own marking</Badge>
            ) : null}
          </div>
        </CardContent>
      </Card>

      {marking && job ? (
        <GradingStatus goalId={goalId} itemId={itemId} attemptId={result.id} job={job} />
      ) : null}

      {markingFailed ? (
        <Alert variant="destructive">
          <CircleAlertIcon aria-hidden="true" />
          <AlertTitle>Your short answers haven&rsquo;t been marked</AlertTitle>
          <AlertDescription>
            <p>
              {job?.error_message ??
                "The marking stopped before it finished. Nothing was lost: your answers are saved."}{" "}
              You can ask for them to be marked again, or open an answer below and mark it yourself
              against the model answer.
            </p>
            {readOnly ? null : (
              <form action={regradeAction.bind(null, goalId, itemId, result.id)} className="mt-3">
                <SubmitButton size="sm" variant="outline">
                  <RotateCcwIcon aria-hidden="true" />
                  Mark them again
                </SubmitButton>
              </form>
            )}
          </AlertDescription>
        </Alert>
      ) : null}

      {mastery ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">How well you know “{result.item_title}”</CardTitle>
            <CardDescription>
              Counted from every quiz you have taken on this topic, newest first. Newer quizzes
              weigh more, and harder questions weigh more.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            <MasteryMeter mastery={mastery} detailed />
            {mastery.objectives.length > 0 ? (
              <div className="space-y-2">
                <h2 className="text-sm font-medium">Score by learning objective</h2>
                <ul className="space-y-2 text-sm">
                  {mastery.objectives.map((objective) => (
                    <li key={objective.id} className="flex items-start justify-between gap-4">
                      <span>{objective.text ?? objective.id}</span>
                      <Badge
                        variant={
                          objective.score < mastery.needs_practice_below ? "warning" : "outline"
                        }
                      >
                        {formatPercent(objective.score)}
                        {objective.score < mastery.needs_practice_below ? " · weak" : ""}
                      </Badge>
                    </li>
                  ))}
                </ul>
                {weak.length > 0 ? (
                  <p className="text-sm text-muted-foreground">
                    The parts marked &ldquo;weak&rdquo; are where the next practice quiz will aim.
                  </p>
                ) : null}
              </div>
            ) : null}
          </CardContent>
        </Card>
      ) : null}

      {result.recommendation ? (
        <RecommendationCard
          goalId={goalId}
          recommendation={result.recommendation}
          readOnly={readOnly}
        />
      ) : null}

      <section aria-labelledby="review-heading" className="space-y-4">
        <h2 id="review-heading" className="font-heading text-xl font-semibold tracking-tight">
          Question by question
        </h2>
        <ol className="space-y-5">
          {result.answers.map((answer, index) => (
            <AnswerReview
              key={answer.id}
              goalId={goalId}
              itemId={itemId}
              attemptId={result.id}
              number={index + 1}
              answer={answer}
              readOnly={readOnly}
            />
          ))}
        </ol>
      </section>
    </div>
  );
}
