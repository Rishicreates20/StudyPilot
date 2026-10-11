"use client";

import Link from "next/link";
import { useActionState } from "react";

import { CheckboxGroup } from "@/components/forms/checkbox-group";
import { DailyMinutesField } from "@/components/forms/daily-minutes-field";
import { FormAlert } from "@/components/forms/form-alert";
import { SubmitButton } from "@/components/forms/submit-button";
import { GoalBasicsFields } from "@/components/goals/goal-basics-fields";
import { Button } from "@/components/ui/button";
import { LANGUAGE_OPTIONS, LEARNING_PREFERENCE_OPTIONS } from "@/lib/goals/options";
import type { GoalFormState, GoalFormValues } from "@/lib/goals/schema";

const INITIAL_STATE: GoalFormState = { status: "idle" };

type GoalFormProps = {
  /** The Server Action that saves the form (create, or update bound to one goal). */
  action: (state: GoalFormState, formData: FormData) => Promise<GoalFormState>;
  /** What the fields start with: the learner's saved preferences, or the goal being edited. */
  defaults: GoalFormValues;
  submitLabel: string;
  cancelHref: string;
};

/** Create or edit a goal. The same form serves both; only the action and the defaults differ. */
export function GoalForm({ action, defaults, submitLabel, cancelHref }: GoalFormProps) {
  const [state, formAction] = useActionState(action, INITIAL_STATE);
  const failed = state.status === "error";
  const errors = failed ? state.fieldErrors : {};
  const values = failed ? state.values : defaults;

  return (
    <form action={formAction} className="space-y-6">
      {failed && state.formError ? <FormAlert message={state.formError} /> : null}

      <GoalBasicsFields values={values} errors={errors} />

      <DailyMinutesField defaultValue={values.dailyMinutes} error={errors.dailyMinutes} />

      <CheckboxGroup
        legend="Languages for your material"
        name="languages"
        options={LANGUAGE_OPTIONS}
        selected={values.languages}
        error={errors.languages}
      />

      <CheckboxGroup
        legend="How you like to learn"
        name="learningPreferences"
        options={LEARNING_PREFERENCE_OPTIONS}
        selected={values.learningPreferences}
        error={errors.learningPreferences}
      />

      <div className="flex flex-wrap items-center gap-3">
        <SubmitButton size="lg">{submitLabel}</SubmitButton>
        <Button asChild variant="ghost" size="lg">
          <Link href={cancelHref}>Cancel</Link>
        </Button>
      </div>
    </form>
  );
}
