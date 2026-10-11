"use client";

import { CircleCheckIcon } from "lucide-react";
import { useActionState } from "react";

import { CheckboxGroup } from "@/components/forms/checkbox-group";
import { DailyMinutesField } from "@/components/forms/daily-minutes-field";
import { FormAlert } from "@/components/forms/form-alert";
import { FormField } from "@/components/forms/form-field";
import { SubmitButton } from "@/components/forms/submit-button";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { LANGUAGE_OPTIONS, LEARNING_PREFERENCE_OPTIONS } from "@/lib/goals/options";
import { saveSettingsAction } from "@/lib/profile/actions";
import type { SettingsState, SettingsValues } from "@/lib/profile/schema";

const IDLE: SettingsState = { status: "idle" };

type SettingsFormProps = {
  defaults: SettingsValues;
  /** IANA timezone names to choose from. */
  timeZones: readonly string[];
};

/** The learner's profile and saved preferences. New goals start from these. */
export function SettingsForm({ defaults, timeZones }: SettingsFormProps) {
  const [state, formAction] = useActionState(saveSettingsAction, IDLE);
  const failed = state.status === "error";
  const errors = failed ? state.fieldErrors : {};
  // After a save the form resets to its defaults, so it must start from what was just saved.
  const values =
    state.status === "error"
      ? state.values
      : state.status === "success" && state.values
        ? state.values
        : defaults;
  // A name the runtime doesn't list (rare) must still be selectable, or saving would change it.
  const zones = timeZones.includes(values.timezone) ? timeZones : [values.timezone, ...timeZones];

  return (
    <form action={formAction} className="space-y-6">
      {state.status === "success" ? (
        <Alert variant="success">
          <CircleCheckIcon aria-hidden="true" />
          <AlertDescription>{state.message}</AlertDescription>
        </Alert>
      ) : null}
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

      <FormField
        label="Your timezone"
        hint="Dates such as 'completed on' are shown in this timezone."
        error={errors.timezone}
        className="sm:max-w-sm"
      >
        {(control) => (
          <NativeSelect
            {...control}
            key={values.timezone}
            name="timezone"
            defaultValue={values.timezone}
          >
            {zones.map((zone) => (
              <option key={zone} value={zone}>
                {zone.replaceAll("_", " ")}
              </option>
            ))}
          </NativeSelect>
        )}
      </FormField>

      <DailyMinutesField
        label="Usual minutes of study per day"
        defaultValue={values.dailyMinutes}
        error={errors.dailyMinutes}
      />

      <CheckboxGroup
        legend="Languages you study in"
        name="languages"
        options={LANGUAGE_OPTIONS}
        selected={values.languages}
        error={errors.languages}
      />

      <CheckboxGroup
        legend="What helps you learn"
        name="learningPreferences"
        options={LEARNING_PREFERENCE_OPTIONS}
        selected={values.learningPreferences}
        error={errors.learningPreferences}
      />

      <p className="text-sm text-muted-foreground">
        These are the starting point for new goals. Goals you have already created keep their own
        settings.
      </p>

      <SubmitButton size="lg">Save preferences</SubmitButton>
    </form>
  );
}
