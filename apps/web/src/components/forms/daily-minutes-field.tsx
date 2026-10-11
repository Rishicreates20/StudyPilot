import { FormField } from "@/components/forms/form-field";
import { Input } from "@/components/ui/input";
import { MAX_DAILY_MINUTES, MIN_DAILY_MINUTES } from "@/lib/goals/options";

type DailyMinutesFieldProps = {
  label?: string;
  defaultValue: string;
  error?: string | undefined;
};

/** How many minutes a day the learner can study. Used by goals, onboarding and settings. */
export function DailyMinutesField({
  label = "Minutes you can study each day",
  defaultValue,
  error,
}: DailyMinutesFieldProps) {
  return (
    <FormField
      label={label}
      hint={`Between ${MIN_DAILY_MINUTES} and ${MAX_DAILY_MINUTES}.`}
      error={error}
      className="sm:max-w-56"
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
          defaultValue={defaultValue}
        />
      )}
    </FormField>
  );
}
