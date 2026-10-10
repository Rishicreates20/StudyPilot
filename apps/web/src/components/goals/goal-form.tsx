"use client";

import Link from "next/link";
import { useActionState } from "react";

import { FormAlert } from "@/components/forms/form-alert";
import { FormField } from "@/components/forms/form-field";
import { SubmitButton } from "@/components/forms/submit-button";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { Textarea } from "@/components/ui/textarea";
import { createGoalAction } from "@/lib/goals/actions";
import {
  DEFAULT_DAILY_MINUTES,
  GOAL_LEVEL_OPTIONS,
  GOAL_TYPE_OPTIONS,
  LANGUAGE_OPTIONS,
  MAX_DAILY_MINUTES,
  MIN_DAILY_MINUTES,
} from "@/lib/goals/options";
import type { GoalFormState, GoalFormValues } from "@/lib/goals/schema";

const INITIAL_STATE: GoalFormState = { status: "idle" };

const DEFAULT_VALUES: GoalFormValues = {
  title: "",
  description: "",
  goalType: "professional_skill",
  currentLevel: "unknown",
  targetDate: "",
  dailyMinutes: String(DEFAULT_DAILY_MINUTES),
  languages: ["en"],
};

export function GoalForm() {
  const [state, formAction] = useActionState(createGoalAction, INITIAL_STATE);
  const failed = state.status === "error";
  const errors = failed ? state.fieldErrors : {};
  const values = failed ? state.values : DEFAULT_VALUES;

  return (
    <form action={formAction} className="space-y-6">
      {failed && state.formError ? <FormAlert message={state.formError} /> : null}

      <FormField
        label="What do you want to learn?"
        hint="For example: Kubernetes for technical interviews."
        error={errors.title}
      >
        {(control) => (
          <Input {...control} name="title" required maxLength={200} defaultValue={values.title} />
        )}
      </FormField>

      <FormField
        label="Anything we should know?"
        optional
        hint="Your syllabus, your job, what you already tried."
        error={errors.description}
      >
        {(control) => (
          <Textarea
            {...control}
            name="description"
            maxLength={2000}
            defaultValue={values.description}
          />
        )}
      </FormField>

      {/* The selects are keyed by their value: React does not re-sync a <select>'s default after
          the form resets, so without the key a server error would silently put the choice back. */}
      <div className="grid gap-6 sm:grid-cols-2">
        <FormField label="This goal is" error={errors.goalType}>
          {(control) => (
            <NativeSelect
              {...control}
              key={values.goalType}
              name="goalType"
              defaultValue={values.goalType}
            >
              {GOAL_TYPE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </NativeSelect>
          )}
        </FormField>

        <FormField label="Your level today" error={errors.currentLevel}>
          {(control) => (
            <NativeSelect
              {...control}
              key={values.currentLevel}
              name="currentLevel"
              defaultValue={values.currentLevel}
            >
              {GOAL_LEVEL_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </NativeSelect>
          )}
        </FormField>

        <FormField
          label="Minutes you can study each day"
          hint={`Between ${MIN_DAILY_MINUTES} and ${MAX_DAILY_MINUTES}.`}
          error={errors.dailyMinutes}
        >
          {(control) => (
            <Input
              {...control}
              name="dailyMinutes"
              type="number"
              inputMode="numeric"
              min={MIN_DAILY_MINUTES}
              max={MAX_DAILY_MINUTES}
              step={5}
              required
              defaultValue={values.dailyMinutes}
            />
          )}
        </FormField>

        <FormField
          label="Target date"
          optional
          hint="When you want to be ready."
          error={errors.targetDate}
        >
          {(control) => (
            <Input {...control} name="targetDate" type="date" defaultValue={values.targetDate} />
          )}
        </FormField>
      </div>

      <fieldset
        className="space-y-3"
        aria-describedby={errors.languages ? "languages-error" : undefined}
      >
        <legend className="text-sm leading-none font-medium">Languages for your material</legend>
        <div className="flex flex-wrap gap-x-6 gap-y-3">
          {LANGUAGE_OPTIONS.map((option) => (
            <label key={option.value} className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                name="languages"
                value={option.value}
                defaultChecked={values.languages.includes(option.value)}
                className="size-4 rounded border-input accent-primary"
              />
              {option.label}
            </label>
          ))}
        </div>
        {errors.languages ? (
          <p
            id="languages-error"
            role="alert"
            className="text-sm font-medium text-destructive-foreground"
          >
            {errors.languages}
          </p>
        ) : null}
      </fieldset>

      <div className="flex flex-wrap items-center gap-3">
        <SubmitButton size="lg">Create goal</SubmitButton>
        <Button asChild variant="ghost" size="lg">
          <Link href="/dashboard">Cancel</Link>
        </Button>
      </div>
    </form>
  );
}
