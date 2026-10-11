"use client";

import { SendIcon } from "lucide-react";
import { useId, useState, type FormEvent } from "react";

import { SubmitButton } from "@/components/forms/submit-button";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import type { QuizDetail } from "@/lib/api/server";
import { submitQuizAction } from "@/lib/quizzes/actions";
import { answerField, MAX_ANSWER_CHARS } from "@/lib/quizzes/answers";
import { difficultyLabel, kindLabel, pointsLabel } from "@/lib/quizzes/labels";
import { countAnswered } from "@/lib/quizzes/state";

type QuizFormProps = {
  goalId: string;
  itemId: string;
  quiz: QuizDetail;
};

/** The values currently filled in, by question id. */
function readValues(form: HTMLFormElement, quiz: QuizDetail): Map<string, string> {
  const data = new FormData(form);
  const values = new Map<string, string>();
  for (const question of quiz.questions) {
    const value = data.get(answerField(question.id));
    if (typeof value === "string") values.set(question.id, value);
  }
  return values;
}

/**
 * The questions of a quiz as a native form: a radio group for each multiple-choice and true/false
 * question, a text box for each short answer. Nothing here knows which answer is right (the API
 * never sends it); submitting posts to a Server Action, which sends the answers on and shows the
 * results. A live count says how many questions are answered, and that blanks count as zero.
 */
export function QuizForm({ goalId, itemId, quiz }: QuizFormProps) {
  const formId = useId();
  const [answered, setAnswered] = useState(0);
  const total = quiz.questions.length;

  function onChange(event: FormEvent<HTMLFormElement>) {
    setAnswered(countAnswered(quiz.questions, readValues(event.currentTarget, quiz)));
  }

  return (
    <form
      action={submitQuizAction.bind(null, goalId, itemId, quiz.id)}
      onChange={onChange}
      className="space-y-6"
      aria-label={`Quiz: ${quiz.title}`}
    >
      <ol className="space-y-6">
        {quiz.questions.map((question, index) => {
          const field = answerField(question.id);
          const promptId = `${formId}-${question.id}-prompt`;
          return (
            <li key={question.id}>
              <fieldset
                className="space-y-4 rounded-xl border bg-card p-5 shadow-xs"
                aria-labelledby={promptId}
              >
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="secondary">{kindLabel(question.kind)}</Badge>
                  <Badge variant="outline">{difficultyLabel(question.difficulty)}</Badge>
                  <Badge variant="outline">{pointsLabel(question.max_points)}</Badge>
                </div>
                <p id={promptId} className="text-base font-medium">
                  <span className="mr-2 text-muted-foreground tabular-nums">{index + 1}.</span>
                  {question.prompt}
                </p>
                {question.objective_text ? (
                  <p className="text-xs text-muted-foreground">Tests: {question.objective_text}</p>
                ) : null}

                {question.options ? (
                  <div className="space-y-2">
                    {question.options.map((option) => (
                      <label
                        key={option.id}
                        className="flex cursor-pointer items-start gap-3 rounded-lg border bg-background p-3 text-sm transition-colors has-[:checked]:border-primary has-[:checked]:bg-primary/5 has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring"
                      >
                        <input
                          type="radio"
                          name={field}
                          value={option.id}
                          className="mt-0.5 size-4 accent-primary"
                        />
                        <span>{option.text}</span>
                      </label>
                    ))}
                  </div>
                ) : (
                  <div className="space-y-2">
                    <Textarea
                      name={field}
                      maxLength={MAX_ANSWER_CHARS}
                      rows={4}
                      aria-labelledby={promptId}
                      placeholder="Write your answer in your own words…"
                    />
                    <p className="text-xs text-muted-foreground">
                      Marked against a rubric after you submit. That marking is an AI estimate, and
                      you can review it yourself.
                    </p>
                  </div>
                )}
              </fieldset>
            </li>
          );
        })}
      </ol>

      <div className="flex flex-col gap-3 rounded-xl border bg-card p-5 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-sm" role="status" aria-live="polite">
          <span className="font-medium tabular-nums">
            {answered} of {total}
          </span>{" "}
          answered.{" "}
          <span className="text-muted-foreground">
            {answered < total
              ? "A question left blank scores zero."
              : "Ready when you are: a quiz can be submitted once."}
          </span>
        </p>
        <SubmitButton size="lg">
          <SendIcon aria-hidden="true" />
          Submit answers
        </SubmitButton>
      </div>
    </form>
  );
}
