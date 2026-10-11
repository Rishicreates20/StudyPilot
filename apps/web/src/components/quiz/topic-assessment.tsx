import {
  ArrowRightIcon,
  CircleAlertIcon,
  ClipboardCheckIcon,
  InfoIcon,
  RotateCcwIcon,
} from "lucide-react";
import Link from "next/link";

import { SubmitButton } from "@/components/forms/submit-button";
import { MasteryMeter } from "@/components/quiz/mastery";
import { QuizGenerationStatus } from "@/components/quiz/quiz-generation-status";
import { RecommendationCard } from "@/components/quiz/recommendation-card";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { TopicAssessment as TopicAssessmentData } from "@/lib/api/server";
import { formatMoment } from "@/lib/format";
import { retryQuizAction, startQuizAction } from "@/lib/quizzes/actions";
import { formatPercent } from "@/lib/quizzes/labels";
import { quizPath, resultsPath } from "@/lib/quizzes/paths";
import { assessmentCardState, blockedText } from "@/lib/quizzes/state";

type TopicAssessmentProps = {
  goalId: string;
  itemId: string;
  assessment: TopicAssessmentData;
  timeZone: string;
};

/**
 * "Check what you've learned": a quiz for the topic, from the lesson. It shows the one thing that
 * can be done now (write a quiz, wait for it, take it, retry a failed one), the result of the last
 * quiz, how well the topic is known, and the recommended next step when this topic needs work.
 */
export function TopicAssessment({ goalId, itemId, assessment, timeZone }: TopicAssessmentProps) {
  const state = assessmentCardState(assessment);
  const { mastery, last_attempt: last, recommendation } = assessment;
  const readOnly = assessment.blocked_by === "goal_archived";
  const needsPractice = mastery?.band === "needs_practice";
  // The recommendation card carries the practice button (or the link to the waiting quiz) for this
  // topic, so the plain cards step aside rather than offering the same thing twice.
  const recommended = needsPractice && recommendation?.item_id === itemId;

  return (
    <section aria-labelledby="quiz-heading" className="space-y-4">
      <h2 id="quiz-heading" className="font-heading text-xl font-semibold tracking-tight">
        Check what you&rsquo;ve learned
      </h2>

      {state.kind === "writing" ? (
        <QuizGenerationStatus goalId={goalId} itemId={itemId} job={state.job} />
      ) : null}

      {state.kind === "failed" ? (
        <Alert variant="destructive">
          <CircleAlertIcon aria-hidden="true" />
          <AlertTitle>We couldn&rsquo;t write the quiz</AlertTitle>
          <AlertDescription>
            <p>{state.job.error_message ?? "Something went wrong. Please try again."}</p>
            <form
              action={retryQuizAction.bind(null, goalId, itemId, state.job.id)}
              className="mt-3"
            >
              <SubmitButton size="sm" variant="outline">
                <RotateCcwIcon aria-hidden="true" />
                Try again
              </SubmitButton>
            </form>
          </AlertDescription>
        </Alert>
      ) : null}

      {state.kind === "ready" && !(recommended && recommendation?.quiz_id === state.quizId) ? (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <ClipboardCheckIcon className="size-5 text-primary" aria-hidden="true" />
              Your quiz is ready
            </CardTitle>
            <CardDescription>
              A few questions on this topic. Answers and explanations appear after you submit.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button asChild>
              <Link href={quizPath(goalId, itemId, state.quizId)}>
                Take the quiz
                <ArrowRightIcon aria-hidden="true" />
              </Link>
            </Button>
          </CardContent>
        </Card>
      ) : null}

      {state.kind === "idle" && !recommended ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">
              {last ? "Practise this topic again" : "Take a short quiz"}
            </CardTitle>
            <CardDescription>
              {last
                ? "A new quiz asks new questions, and aims at the parts that scored lowest."
                : "About five questions written from your lesson. You see the right answers and why after you submit."}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form action={startQuizAction.bind(null, goalId, itemId, last ? "practice" : "check")}>
              <SubmitButton>
                <ClipboardCheckIcon aria-hidden="true" />
                {last ? "Take another quiz" : "Take a quiz"}
              </SubmitButton>
            </form>
          </CardContent>
        </Card>
      ) : null}

      {state.kind === "blocked" ? (
        <Alert variant="info">
          <InfoIcon aria-hidden="true" />
          <AlertDescription>{blockedText(state.reason)}</AlertDescription>
        </Alert>
      ) : null}

      {mastery ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">How well you know this topic</CardTitle>
            {last ? (
              <CardDescription>
                Last quiz:{" "}
                {last.percent === null
                  ? "waiting for its short answers to be marked"
                  : formatPercent(last.percent)}
                , {formatMoment(last.submitted_at, timeZone)}.
              </CardDescription>
            ) : null}
          </CardHeader>
          <CardContent className="space-y-4">
            <MasteryMeter mastery={mastery} label="Mastery of this topic" detailed />
            {last ? (
              <Button asChild variant="outline" size="sm">
                <Link href={resultsPath(goalId, itemId, last.id)}>See your last results</Link>
              </Button>
            ) : null}
            {mastery.objectives.length > 1 ? (
              <ul className="space-y-1.5 text-sm" aria-label="Score by learning objective">
                {mastery.objectives.map((objective) => (
                  <li key={objective.id} className="flex items-start justify-between gap-4">
                    <span>{objective.text ?? objective.id}</span>
                    <Badge
                      variant={
                        objective.score < mastery.needs_practice_below ? "warning" : "outline"
                      }
                    >
                      {formatPercent(objective.score)}
                    </Badge>
                  </li>
                ))}
              </ul>
            ) : null}
          </CardContent>
        </Card>
      ) : last ? (
        <p className="text-sm text-muted-foreground">
          <Link
            href={resultsPath(goalId, itemId, last.id)}
            className="font-medium text-primary underline-offset-4 hover:underline"
          >
            See your results
          </Link>{" "}
          (some short answers are still being marked).
        </p>
      ) : null}

      {recommended && recommendation ? (
        <RecommendationCard goalId={goalId} recommendation={recommendation} readOnly={readOnly} />
      ) : null}
    </section>
  );
}
