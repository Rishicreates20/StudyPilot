"use client";

import { CircleAlertIcon, RotateCcwIcon } from "lucide-react";

import { Alert, AlertAction, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

type ErrorStateProps = {
  title?: string;
  description?: string;
  /** Provide a retry handler to show a "Try again" action. */
  onRetry?: () => void;
  retrying?: boolean;
  /** An error or request ID to quote to support; shown when provided. */
  reference?: string;
};

export function ErrorState({
  title = "Something went wrong",
  description = "We couldn't complete that. Please try again.",
  onRetry,
  retrying = false,
  reference,
}: ErrorStateProps) {
  return (
    <Alert variant="destructive">
      <CircleAlertIcon aria-hidden="true" />
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription>
        <p>{description}</p>
        {reference ? (
          <p className="mt-2 font-mono text-xs">
            Reference: <span className="select-all">{reference}</span>
          </p>
        ) : null}
      </AlertDescription>
      {onRetry ? (
        <AlertAction>
          <Button variant="outline" size="sm" onClick={onRetry} loading={retrying}>
            {retrying ? null : <RotateCcwIcon aria-hidden="true" />}
            Try again
          </Button>
        </AlertAction>
      ) : null}
    </Alert>
  );
}
