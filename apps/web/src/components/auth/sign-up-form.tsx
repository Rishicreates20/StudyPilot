"use client";

import { MailCheckIcon } from "lucide-react";
import Link from "next/link";
import { useActionState } from "react";

import { FormAlert } from "@/components/forms/form-alert";
import { FormField } from "@/components/forms/form-field";
import { SubmitButton } from "@/components/forms/submit-button";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { signUpAction, type SignUpState } from "@/lib/auth/actions";
import { MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH } from "@/lib/auth/schemas";

const INITIAL_STATE: SignUpState = { status: "idle" };

export function SignUpForm() {
  const [state, formAction] = useActionState(signUpAction, INITIAL_STATE);

  if (state.status === "check-email") {
    return (
      <div className="space-y-5">
        <Alert variant="success">
          <MailCheckIcon aria-hidden="true" />
          <AlertTitle>Check your email</AlertTitle>
          <AlertDescription>
            <p>
              If <strong>{state.email}</strong> can be used for a new account, we have sent a link
              to confirm it. Open the link on this device to finish signing up.
            </p>
          </AlertDescription>
        </Alert>
        <Button asChild variant="outline" className="w-full">
          <Link href="/sign-in">Back to sign in</Link>
        </Button>
      </div>
    );
  }

  const failed = state.status === "error";
  const errors = failed ? state.fieldErrors : {};
  const values = failed ? state.values : { displayName: "", email: "" };

  return (
    <form action={formAction} className="space-y-5">
      {failed && state.formError ? <FormAlert message={state.formError} /> : null}

      <FormField label="Your name" optional error={errors.displayName}>
        {(control) => (
          <Input
            {...control}
            name="displayName"
            autoComplete="name"
            maxLength={80}
            defaultValue={values.displayName}
          />
        )}
      </FormField>

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
            defaultValue={values.email}
          />
        )}
      </FormField>

      <FormField
        label="Password"
        hint={`Use ${MIN_PASSWORD_LENGTH} or more characters. A few random words make a strong password.`}
        error={errors.password}
      >
        {(control) => (
          <Input
            {...control}
            name="password"
            type="password"
            autoComplete="new-password"
            minLength={MIN_PASSWORD_LENGTH}
            maxLength={MAX_PASSWORD_LENGTH}
            required
          />
        )}
      </FormField>

      <SubmitButton className="w-full" size="lg">
        Create account
      </SubmitButton>
    </form>
  );
}
