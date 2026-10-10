import type { z } from "zod";

/** Field-level error messages keyed by form field name. */
export type FieldErrors<K extends string> = Partial<Record<K, string>>;

/**
 * The result of a Server Action backing a form, rendered with `useActionState`.
 *
 * `values` echoes back what the user typed (never passwords) because React resets uncontrolled
 * forms after an action completes; the inputs use it as their `defaultValue`.
 */
export type FormState<K extends string, V = Partial<Record<K, string>>> =
  | { readonly status: "idle" }
  | {
      readonly status: "error";
      readonly formError?: string;
      readonly fieldErrors: FieldErrors<K>;
      readonly values: V;
    };

/** The first message for each top-level field of a failed Zod parse. */
export function zodFieldErrors<K extends string>(error: z.ZodError): FieldErrors<K> {
  const errors: Partial<Record<string, string>> = {};
  for (const issue of error.issues) {
    const field = String(issue.path[0] ?? "");
    if (field && errors[field] === undefined) errors[field] = issue.message;
  }
  return errors as FieldErrors<K>;
}

/** A form field as a string ("" when absent or when it is a File). */
export function formString(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value : "";
}
