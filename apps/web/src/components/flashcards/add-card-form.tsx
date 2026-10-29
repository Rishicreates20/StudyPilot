"use client";

import { PlusIcon } from "lucide-react";
import { useActionState } from "react";

import { CardFields } from "@/components/flashcards/card-fields";
import { FormAlert } from "@/components/forms/form-alert";
import { SubmitButton } from "@/components/forms/submit-button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { createFlashcardAction } from "@/lib/flashcards/actions";
import type { CardFormState } from "@/lib/flashcards/schema";

const IDLE = { status: "idle" } as const;

/** Write a new card. It is due at once; the server decides every later date. */
export function AddCardForm({ goalId }: { goalId: string }) {
  const [state, action] = useActionState<CardFormState, FormData>(
    createFlashcardAction.bind(null, goalId),
    IDLE,
  );

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-lg">
          <PlusIcon className="size-5 text-primary" aria-hidden="true" />
          <h2>Add a card</h2>
        </CardTitle>
        <CardDescription>
          One thing to remember per card. It is saved to your account and comes up for review
          straight away.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form action={action} className="space-y-4" noValidate>
          {state.status === "error" && state.formError ? (
            <FormAlert message={state.formError} />
          ) : null}
          <CardFields state={state} defaults={{ front: "", back: "" }} />
          <div className="flex items-center gap-3">
            <SubmitButton>Add card</SubmitButton>
            {state.status === "success" ? (
              <span role="status" className="text-sm text-success-foreground">
                {state.message}
              </span>
            ) : null}
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
