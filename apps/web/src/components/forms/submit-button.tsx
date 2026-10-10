"use client";

import type { ComponentProps } from "react";
import { useFormStatus } from "react-dom";

import { Button } from "@/components/ui/button";

/** A submit button that shows a spinner and blocks double submits while its form is pending. */
export function SubmitButton({
  children,
  ...props
}: Omit<ComponentProps<typeof Button>, "type" | "loading">) {
  const { pending } = useFormStatus();
  return (
    <Button type="submit" loading={pending} {...props}>
      {children}
    </Button>
  );
}
