import { CircleAlertIcon } from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";

/** A form-level failure (not tied to one field). Interrupts assistive technology, like any error. */
export function FormAlert({ message }: { message: string }) {
  return (
    <Alert variant="destructive">
      <CircleAlertIcon aria-hidden="true" />
      <AlertDescription>{message}</AlertDescription>
    </Alert>
  );
}
