"use client";

import { PencilIcon, Trash2Icon } from "lucide-react";
import { useActionState } from "react";

import { CardFields } from "@/components/flashcards/card-fields";
import { FormAlert } from "@/components/forms/form-alert";
import { SubmitButton } from "@/components/forms/submit-button";
import { Badge } from "@/components/ui/badge";
import { deleteFlashcardAction, updateFlashcardAction } from "@/lib/flashcards/actions";
import type { CardFormState } from "@/lib/flashcards/schema";

const IDLE = { status: "idle" } as const;

type CardRowProps = {
  goalId: string;
  cardId: string;
  front: string;
  back: string;
  /** "Due now", "Due tomorrow": worded on the server, from the server's clock. */
  dueLabel: string;
  stage: string;
  /** Archived goals are read-only: the card is shown without its edit and delete controls. */
  readOnly: boolean;
};

/** One card: both sides, when it is due, and (unless the goal is archived) edit and delete. */
export function CardRow({ goalId, cardId, front, back, dueLabel, stage, readOnly }: CardRowProps) {
  return (
    <li className="space-y-3 rounded-xl border bg-card p-4">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="secondary">{stage}</Badge>
        <span className="text-sm text-muted-foreground">{dueLabel}</span>
      </div>
      <div className="space-y-2">
        <p className="whitespace-pre-wrap text-sm font-medium leading-6">{front}</p>
        <p className="whitespace-pre-wrap text-sm leading-6 text-muted-foreground">{back}</p>
      </div>
      {readOnly ? null : (
        <div className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
          <EditCard goalId={goalId} cardId={cardId} front={front} back={back} />
          <DeleteCard goalId={goalId} cardId={cardId} />
        </div>
      )}
    </li>
  );
}

const SUMMARY =
  "inline-flex cursor-pointer items-center gap-1.5 rounded-sm font-medium text-primary outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background";

function EditCard({
  goalId,
  cardId,
  front,
  back,
}: {
  goalId: string;
  cardId: string;
  front: string;
  back: string;
}) {
  const [state, action] = useActionState<CardFormState, FormData>(
    updateFlashcardAction.bind(null, goalId, cardId),
    IDLE,
  );
  return (
    <details className="w-full">
      <summary className={SUMMARY}>
        <PencilIcon className="size-4" aria-hidden="true" />
        Edit
      </summary>
      <form action={action} className="mt-3 space-y-4" noValidate>
        {state.status === "error" && state.formError ? (
          <FormAlert message={state.formError} />
        ) : null}
        <CardFields state={state} defaults={{ front, back }} />
        <div className="flex items-center gap-3">
          <SubmitButton size="sm">Save card</SubmitButton>
          {state.status === "success" ? (
            <span role="status" className="text-sm text-success-foreground">
              {state.message}
            </span>
          ) : null}
        </div>
      </form>
    </details>
  );
}

function DeleteCard({ goalId, cardId }: { goalId: string; cardId: string }) {
  return (
    <details className="w-full">
      <summary className={SUMMARY}>
        <Trash2Icon className="size-4" aria-hidden="true" />
        Delete
      </summary>
      <form action={deleteFlashcardAction.bind(null, goalId, cardId)} className="mt-3 space-y-3">
        <p className="text-sm">
          Delete this card and its review history? This can&rsquo;t be undone.
        </p>
        <SubmitButton size="sm" variant="destructive">
          Yes, delete the card
        </SubmitButton>
      </form>
    </details>
  );
}
