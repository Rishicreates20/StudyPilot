"use client";

import { useActionState } from "react";

import { FormAlert } from "@/components/forms/form-alert";
import { FormField } from "@/components/forms/form-field";
import { SubmitButton } from "@/components/forms/submit-button";
import { Input } from "@/components/ui/input";
import { signInAction, type SignInState } from "@/lib/auth/actions";

const INITIAL_STATE: SignInState = { status: "idle" };

export function SignInForm({ next }: { next: string }) {
  const [state, formAction] = useActionState(signInAction, INITIAL_STATE);
  const failed = state.status === "error";
  const errors = failed ? state.fieldErrors : {};

  return (
    <form action={formAction} className="space-y-5">
      {failed && state.formError ? <FormAlert message={state.formError} /> : null}
      <input type="hidden" name="next" value={next} />

      <FormField label="Email" error={errors.email}>
        {(control) => (
          <Input
            {...control}
            name="email"
            type="email"
            autoComplete="email"
            autoCapitalize="none"
            spellCheck={false}
            required
            defaultValue={failed ? state.values.email : ""}
          />
        )}
      </FormField>

      <FormField label="Password" error={errors.password}>
        {(control) => (
          <Input
            {...control}
            name="password"
            type="password"
            autoComplete="current-password"
            required
          />
        )}
      </FormField>

      <SubmitButton className="w-full" size="lg">
        Sign in
      </SubmitButton>
    </form>
  );
}
