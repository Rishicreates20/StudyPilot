import { cn } from "cn";
import { useId, type ReactNode } from "react";

import { Label } from "@/components/ui/label";

/** Props to spread onto the control so it is labelled and its error is announced. */
export type FieldControlProps = {
  id: string;
  "aria-describedby": string | undefined;
  "aria-invalid": true | undefined;
};

type FormFieldProps = {
  label: string;
  /** Supporting text shown under the control. */
  hint?: string;
  /** Validation message; when present the control is marked invalid. */
  error?: string | undefined;
  /** Adds "(optional)" to the label. */
  optional?: boolean;
  className?: string;
  children: (control: FieldControlProps) => ReactNode;
};

/**
 * A visible label, the control, a hint and an error, wired together for assistive technology
 * (`for`/`id`, `aria-describedby`, `aria-invalid`). The error is announced politely when it appears.
 */
export function FormField({ label, hint, error, optional, className, children }: FormFieldProps) {
  const id = useId();
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  const describedBy = [error ? errorId : null, hint ? hintId : null].filter(Boolean).join(" ");

  return (
    <div className={cn("space-y-2", className)}>
      <Label htmlFor={id}>
        {label}
        {optional ? <span className="font-normal text-muted-foreground">(optional)</span> : null}
      </Label>
      {children({
        id,
        "aria-describedby": describedBy || undefined,
        "aria-invalid": error ? true : undefined,
      })}
      {hint ? (
        <p id={hintId} className="text-sm text-muted-foreground">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={errorId} role="alert" className="text-sm font-medium text-destructive-foreground">
          {error}
        </p>
      ) : null}
    </div>
  );
}
