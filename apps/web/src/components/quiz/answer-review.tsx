import { CircleCheckIcon, CircleMinusIcon, CircleXIcon } from "lucide-react";
import type { ReactNode } from "react";

import { SubmitButton } from "@/components/forms/submit-button";
import { Badge } from "@/components/ui/badge";
import type { AnswerResult } from "@/lib/api/server";
import {
  difficultyLabel,
  ESTIMATE_NOTE,
  formatPoints,
  gradingMethodLabel,
  kindLabel,
} from "@/lib/quizzes/labels";
import { reviewAnswerAction } from "@/lib/quizzes/actions";

type AnswerReviewProps = {
  goalId: string;
  itemId: string;
  attemptId: string;
  number: number;
  answer: AnswerResult;
  /** The goal is archived: results stay readable, but nothing can be changed. */
  readOnly: boolean;
};

/** Whether a multiple-choice or true/false answer was right, wrong or left blank. */
function Outcome({ answer }: { answer: AnswerResult }): ReactNode {
  if (answer.skipped) {
    return (
      <Badge variant="outline">
        <CircleMinusIcon aria-hidden="true" />
        Not answered
      </Badge>
    );
  }
  if (answer.is_correct) {
    return (
      <Badge variant="success">
        <CircleCheckIcon aria-hidden="true" />
        Correct
      </Badge>
    );
  }
  return (
    <Badge variant="destructive">
      <CircleXIcon aria-hidden="true" />
      Not quite
    </Badge>
  );
}

/**
 * One question of a result: what was asked, what the learner answered, the right answer and why,
 * and for a short answer the rubric, the model answer and the marking, labelled as an estimate with
 * a way for the learner to correct it. Correctness is shown with words and icons, never colour alone.
 */
export function AnswerReview({
  goalId,
  itemId,
  attemptId,
  number,
  answer,
  readOnly,
}: AnswerReviewProps) {
  const shortAnswer = answer.kind === "short_answer";
  const pending = answer.grading_method === "pending";
  const rubric = answer.feedback.rubric ?? [];
  const matched = new Set(answer.feedback.matched_point_ids);

  return (
    <li id={`answer-${answer.id}`} className="scroll-mt-24">
      <article className="space-y-4 rounded-xl border bg-card p-5 shadow-xs">
        <header className="flex flex-wrap items-center gap-2">
          <Badge variant="secondary">{kindLabel(answer.kind)}</Badge>
          <Badge variant="outline">{difficultyLabel(answer.difficulty)}</Badge>
          {shortAnswer && answer.skipped ? (
            <>
              <Outcome answer={answer} />
              <Badge variant="outline">
                0 of {answer.max_points} {answer.max_points === 1 ? "point" : "points"}
              </Badge>
            </>
          ) : shortAnswer ? (
            pending ? (
              <Badge variant="info">Waiting to be marked</Badge>
            ) : (
              <>
                <Badge variant={answer.grading_method === "ai_estimate" ? "warning" : "secondary"}>
                  {gradingMethodLabel(answer.grading_method)}
                </Badge>
                <Badge variant="outline">
                  {formatPoints(answer.points_awarded ?? 0)} of {answer.max_points}{" "}
                  {answer.max_points === 1 ? "point" : "points"}
                </Badge>
              </>
            )
          ) : (
            <Outcome answer={answer} />
          )}
        </header>

        <h3 className="text-base font-medium">
          <span className="mr-2 text-muted-foreground tabular-nums">{number}.</span>
          {answer.prompt}
        </h3>
        {answer.objective_text ? (
          <p className="text-xs text-muted-foreground">Tests: {answer.objective_text}</p>
        ) : null}

        {answer.options ? (
          <ul className="space-y-2" aria-label="Options">
            {answer.options.map((option) => {
              const yours = answer.your_answer.option_id === option.id;
              const right = answer.feedback.correct_option_id === option.id;
              const note = answer.feedback.option_notes[option.id];
              return (
                <li
                  key={option.id}
                  className={
                    right
                      ? "rounded-lg border border-success/40 bg-success-soft p-3 text-sm"
                      : yours
                        ? "rounded-lg border border-destructive/40 bg-destructive-soft p-3 text-sm"
                        : "rounded-lg border p-3 text-sm"
                  }
                >
                  <p className="flex flex-wrap items-center gap-2">
                    <span>{option.text}</span>
                    {right ? (
                      <Badge variant="success">
                        <CircleCheckIcon aria-hidden="true" />
                        Correct answer
                      </Badge>
                    ) : null}
                    {yours ? <Badge variant="outline">Your answer</Badge> : null}
                  </p>
                  {note ? <p className="mt-1.5 text-muted-foreground">{note}</p> : null}
                </li>
              );
            })}
          </ul>
        ) : (
          <div className="space-y-1.5">
            <p className="text-sm font-medium">Your answer</p>
            {answer.skipped ? (
              <p className="text-sm text-muted-foreground">You left this blank.</p>
            ) : (
              <blockquote className="rounded-lg border-l-4 bg-muted/40 p-3 text-sm whitespace-pre-wrap">
                {answer.your_answer.text}
              </blockquote>
            )}
          </div>
        )}

        <div className="space-y-1.5 rounded-lg bg-muted/40 p-3 text-sm">
          <p className="font-medium">Why</p>
          <p>{answer.feedback.explanation}</p>
        </div>

        {shortAnswer ? (
          <div className="space-y-4">
            <div className="space-y-2">
              <p className="text-sm font-medium">What a good answer includes</p>
              <ul className="space-y-1.5 text-sm">
                {rubric.map((point) => {
                  const met = matched.has(point.id);
                  return (
                    <li key={point.id} className="flex items-start gap-2">
                      {pending || answer.skipped ? (
                        <CircleMinusIcon
                          className="mt-0.5 size-4 shrink-0 text-muted-foreground"
                          aria-hidden="true"
                        />
                      ) : met ? (
                        <CircleCheckIcon
                          className="mt-0.5 size-4 shrink-0 text-success-foreground"
                          aria-hidden="true"
                        />
                      ) : (
                        <CircleXIcon
                          className="mt-0.5 size-4 shrink-0 text-destructive-foreground"
                          aria-hidden="true"
                        />
                      )}
                      <span>
                        {point.text}
                        {pending || answer.skipped ? null : (
                          <span className="sr-only">{met ? " (covered)" : " (not covered)"}</span>
                        )}
                      </span>
                    </li>
                  );
                })}
              </ul>
            </div>
            {answer.feedback.model_answer ? (
              <div className="space-y-1.5">
                <p className="text-sm font-medium">A model answer</p>
                <p className="rounded-lg border bg-background p-3 text-sm">
                  {answer.feedback.model_answer}
                </p>
              </div>
            ) : null}
            {answer.feedback.comment && !pending ? (
              <p className="text-sm">
                <span className="font-medium">
                  {answer.grading_method === "self_review" ? "Note: " : "Feedback: "}
                </span>
                {answer.feedback.comment}
              </p>
            ) : null}
            {answer.grading_method === "ai_estimate" ? (
              <p className="text-xs text-muted-foreground">{ESTIMATE_NOTE}</p>
            ) : null}
            {!answer.skipped && !pending && !readOnly ? (
              <details className="rounded-lg border p-3 text-sm">
                <summary className="cursor-pointer font-medium">
                  {answer.grading_method === "self_review"
                    ? "Change your marking"
                    : "Disagree? Mark it yourself"}
                </summary>
                <form
                  action={reviewAnswerAction.bind(null, goalId, itemId, attemptId, answer.id)}
                  className="mt-3 space-y-3"
                >
                  <fieldset className="space-y-2">
                    <legend className="text-muted-foreground">
                      Tick the points your answer really made.
                    </legend>
                    {rubric.map((point) => (
                      <label key={point.id} className="flex items-start gap-2">
                        <input
                          type="checkbox"
                          name="met"
                          value={point.id}
                          defaultChecked={matched.has(point.id)}
                          className="mt-0.5 size-4 rounded border-input accent-primary"
                        />
                        <span>{point.text}</span>
                      </label>
                    ))}
                  </fieldset>
                  <SubmitButton size="sm">Save my marking</SubmitButton>
                </form>
              </details>
            ) : null}
          </div>
        ) : null}
      </article>
    </li>
  );
}
