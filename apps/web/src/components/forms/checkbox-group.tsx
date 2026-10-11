import { cn } from "cn";
import { useId } from "react";

type CheckboxOption = {
  readonly value: string;
  readonly label: string;
  /** Supporting text under the label, announced with the checkbox. */
  readonly hint?: string;
};

type CheckboxGroupProps = {
  legend: string;
  /** The submitted field name; every ticked box is sent under it. */
  name: string;
  options: readonly CheckboxOption[];
  selected: readonly string[];
  error?: string | undefined;
  /** Supporting text under the legend. */
  hint?: string;
  className?: string;
};

/**
 * A labelled group of checkboxes: a `fieldset` and `legend` so assistive technology announces the
 * group, each box with its own label (and optional hint), and the error tied to the group.
 */
export function CheckboxGroup({
  legend,
  name,
  options,
  selected,
  error,
  hint,
  className,
}: CheckboxGroupProps) {
  const id = useId();
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  const describedBy = [error ? errorId : null, hint ? hintId : null].filter(Boolean).join(" ");

  return (
    <fieldset className={cn("space-y-3", className)} aria-describedby={describedBy || undefined}>
      <legend className="text-sm leading-none font-medium">{legend}</legend>
      {hint ? (
        <p id={hintId} className="text-sm text-muted-foreground">
          {hint}
        </p>
      ) : null}
      <div className="flex flex-wrap gap-x-8 gap-y-4">
        {options.map((option) => {
          const optionHintId = `${id}-${option.value}-hint`;
          return (
            <div key={option.value} className="max-w-xs space-y-1">
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  name={name}
                  value={option.value}
                  defaultChecked={selected.includes(option.value)}
                  aria-describedby={option.hint ? optionHintId : undefined}
                  className="size-4 rounded border-input accent-primary"
                />
                {option.label}
              </label>
              {option.hint ? (
                <p id={optionHintId} className="pl-6 text-xs text-muted-foreground">
                  {option.hint}
                </p>
              ) : null}
            </div>
          );
        })}
      </div>
      {error ? (
        <p id={errorId} role="alert" className="text-sm font-medium text-destructive-foreground">
          {error}
        </p>
      ) : null}
    </fieldset>
  );
}
