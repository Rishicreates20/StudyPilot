"use client";

import Link from "next/link";
import { useActionState } from "react";

import { CheckboxGroup } from "@/components/forms/checkbox-group";
import { DailyMinutesField } from "@/components/forms/daily-minutes-field";
import { FormAlert } from "@/components/forms/form-alert";
import { FormField } from "@/components/forms/form-field";
import { SubmitButton } from "@/components/forms/submit-button";
import { GoalBasicsFields } from "@/components/goals/goal-basics-fields";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { LANGUAGE_OPTIONS, LEARNING_PREFERENCE_OPTIONS } from "@/lib/goals/options";
import type { GoalFormState, GoalFormValues } from "@/lib/goals/schema";
import {
  createFirstGoalAction,
  saveAboutYouAction,
  saveStudyStyleAction,
  skipOnboardingAction,
} from "@/lib/onboarding/actions";
import { onboardingStepPath } from "@/lib/onboarding/paths";
import type { SettingsState, SettingsValues } from "@/lib/profile/schema";

const IDLE = { status: "idle" } as const;

/** Step 1: what to call the learner and which languages they study in. */
export function AboutYouForm({ defaults }: { defaults: SettingsValues }) {
  const [state, formAction] = useActionState<SettingsState, FormData>(saveAboutYouAction, IDLE);
  const failed = state.status === "error";
  const errors = failed ? state.fieldErrors : {};
  const values = failed ? state.values : defaults;

  return (
    <form action={formAction} className="space-y-6">
      {failed && state.formError ? <FormAlert message={state.formError} /> : null}

      <FormField label="What should we call you?" optional error={errors.displayName}>
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

      <CheckboxGroup
        legend="Which languages do you study in?"
        hint="Choose all that suit you. You can change this for each goal later."
        name="languages"
        options={LANGUAGE_OPTIONS}
        selected={values.languages}
        error={errors.languages}
      />

      <SubmitButton size="lg">Continue</SubmitButton>
    </form>
  );
}

/** Step 2: how much time there is each day and what kind of practice the learner wants. */
export function StudyStyleForm({ defaults }: { defaults: SettingsValues }) {
  const [state, formAction] = useActionState<SettingsState, FormData>(saveStudyStyleAction, IDLE);
  const failed = state.status === "error";
  const errors = failed ? state.fieldErrors : {};
  const values = failed ? state.values : defaults;

  return (
    <form action={formAction} className="space-y-6">
      {failed && state.formError ? <FormAlert message={state.formError} /> : null}

      <DailyMinutesField
        label="How many minutes can you study on a typical day?"
        defaultValue={values.dailyMinutes}
        error={errors.dailyMinutes}
      />

      <CheckboxGroup
        legend="What helps you learn?"
        hint="Pick any you like, or none. These shape how your lessons are put together."
        name="learningPreferences"
        options={LEARNING_PREFERENCE_OPTIONS}
        selected={values.learningPreferences}
        error={errors.learningPreferences}
      />

      <div className="flex flex-wrap items-center gap-3">
        <SubmitButton size="lg">Continue</SubmitButton>
        <Button asChild variant="ghost" size="lg">
          <Link href={onboardingStepPath(1)}>Back</Link>
        </Button>
      </div>
    </form>
  );
}

/** Step 3: the first goal. Only the essentials; the target date is optional. */
export function FirstGoalForm({ defaults }: { defaults: GoalFormValues }) {
  const [state, formAction] = useActionState<GoalFormState, FormData>(createFirstGoalAction, IDLE);
  const failed = state.status === "error";
  const errors = failed ? state.fieldErrors : {};
  const values = failed ? state.values : defaults;

  return (
    <form action={formAction} className="space-y-6">
      {failed && state.formError ? <FormAlert message={state.formError} /> : null}

      <GoalBasicsFields values={values} errors={errors} />

      <div className="flex flex-wrap items-center gap-3">
        <SubmitButton size="lg">Create my first goal</SubmitButton>
        <Button asChild variant="ghost" size="lg">
          <Link href={onboardingStepPath(2)}>Back</Link>
        </Button>
      </div>
    </form>
  );
}

/** "Skip for now": its own form, because forms cannot be nested inside each other. */
export function SkipOnboardingButton() {
  return (
    <form action={skipOnboardingAction}>
      <SubmitButton variant="ghost" size="sm">
        Skip for now
      </SubmitButton>
    </form>
  );
}
