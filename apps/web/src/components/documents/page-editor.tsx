"use client";

import { SaveIcon } from "lucide-react";
import { useActionState } from "react";

import { FormAlert } from "@/components/forms/form-alert";
import { FormField } from "@/components/forms/form-field";
import { SubmitButton } from "@/components/forms/submit-button";
import { Textarea } from "@/components/ui/textarea";
import { savePageAction } from "@/lib/documents/actions";
import type { PageFormState } from "@/lib/documents/schema";

const IDLE = { status: "idle" } as const;

/** Correct what was read from a picture. Saved page by page; nothing is used until confirmed. */
export function PageEditor({
  goalId,
  documentId,
  pageNumber,
  label,
  text,
}: {
  goalId: string;
  documentId: string;
  pageNumber: number;
  /** "Page 2": names the field for assistive technology. */
  label: string;
  text: string;
}) {
  const [state, action] = useActionState<PageFormState, FormData>(
    savePageAction.bind(null, goalId, documentId, pageNumber),
    IDLE,
  );
  const shown = state.status === "idle" ? text : (state.values?.text ?? text);

  return (
    <form action={action} className="space-y-3" noValidate>
      {state.status === "error" && state.formError ? <FormAlert message={state.formError} /> : null}
      <FormField
        label={`Text of ${label.toLowerCase()}`}
        error={state.status === "error" ? state.fieldErrors.text : undefined}
      >
        {(control) => (
          <Textarea
            {...control}
            name="text"
            key={shown}
            defaultValue={shown}
            rows={Math.min(16, Math.max(5, shown.split("\n").length + 1))}
          />
        )}
      </FormField>
      <div className="flex items-center gap-3">
        <SubmitButton variant="outline" size="sm">
          <SaveIcon aria-hidden="true" />
          Save changes
        </SubmitButton>
        {state.status === "success" ? (
          <span role="status" className="text-sm text-success-foreground">
            {state.message}
          </span>
        ) : null}
      </div>
    </form>
  );
}
