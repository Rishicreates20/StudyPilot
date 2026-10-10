import { CircleAlertIcon, RotateCcwIcon } from "lucide-react";
import Link from "next/link";

import { Alert, AlertAction, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

type LoadErrorProps = {
  title: string;
  description: string;
  /** Where "Try again" goes (usually the current page). */
  retryHref: string;
  /** The API's request ID, so a report can be matched to server logs. */
  reference?: string | undefined;
};

/**
 * A server-rendered failure with a retry link: for data that failed to load in a Server
 * Component, where a client-side retry callback is not available.
 */
export function LoadError({ title, description, retryHref, reference }: LoadErrorProps) {
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
      <AlertAction>
        <Button asChild variant="outline" size="sm">
          <Link href={retryHref}>
            <RotateCcwIcon aria-hidden="true" />
            Try again
          </Link>
        </Button>
      </AlertAction>
    </Alert>
  );
}
