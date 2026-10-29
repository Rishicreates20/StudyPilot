"use client";

import { FormField } from "@/components/forms/form-field";
import { Textarea } from "@/components/ui/textarea";
import { MAX_BACK_CHARS, MAX_FRONT_CHARS, type CardFormState } from "@/lib/flashcards/schema";

/** The two sides of a card, with the server's field errors and what was typed put back. */
export function CardFields({
  state,
  defaults,
}: {
  state: CardFormState;
  /** Shown before anything has been submitted (an existing card's text, or empty). */
  defaults: { front: string; back: string };
}) {
  const values = state.status === "idle" ? defaults : (state.values ?? defaults);
  const errors = state.status === "error" ? state.fieldErrors : {};
  return (
    <>
      <FormField label="Front" hint="The question or prompt." error={errors.front}>
        {(control) => (
          <Textarea
            {...control}
            name="front"
            rows={3}
            maxLength={MAX_FRONT_CHARS}
            defaultValue={values.front}
            key={`front-${values.front}`}
          />
        )}
      </FormField>
      <FormField label="Back" hint="The answer you want to remember." error={errors.back}>
        {(control) => (
          <Textarea
            {...control}
            name="back"
            rows={4}
            maxLength={MAX_BACK_CHARS}
            defaultValue={values.back}
            key={`back-${values.back}`}
          />
        )}
      </FormField>
    </>
  );
}
