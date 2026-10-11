import { FormField } from "@/components/forms/form-field";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { Textarea } from "@/components/ui/textarea";
import { GOAL_LEVEL_OPTIONS, GOAL_TYPE_OPTIONS } from "@/lib/goals/options";
import type { GoalFormField, GoalFormValues } from "@/lib/goals/schema";

type GoalBasicsFieldsProps = {
  values: GoalFormValues;
  errors: Partial<Record<GoalFormField, string>>;
};

/**
 * What the goal is: title, notes, kind, current level and the (optional) target date. Shared by
 * the create and edit forms and by the first goal in onboarding.
 */
export function GoalBasicsFields({ values, errors }: GoalBasicsFieldsProps) {
  return (
    <>
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
          label="Target date"
          optional
          hint="When you want to be ready. Leave it empty if there is no deadline."
          error={errors.targetDate}
          className="sm:col-span-2"
        >
          {(control) => (
            <Input
              {...control}
              name="targetDate"
              type="date"
              defaultValue={values.targetDate}
              className="sm:max-w-56"
            />
          )}
        </FormField>
      </div>
    </>
  );
}
