"use client";

import { useEffect } from "react";

import { ErrorState } from "@/components/feedback/error-state";
import { PageContainer } from "@/components/layout/page";

/** Route-level error boundary: a calm message and a retry, never a stack trace. */
export default function RouteError({
  error,
  retry,
}: {
  error: Error & { digest?: string };
  retry: () => void;
}) {
  useEffect(() => {
    // Replace with the error-tracking client (Sentry) when it is introduced.
    console.error(error);
  }, [error]);

  return (
    <PageContainer className="py-16">
      <ErrorState
        title="This page hit a problem"
        description="Your data is safe. Try again, and if it keeps happening let us know."
        reference={error.digest}
        onRetry={retry}
      />
    </PageContainer>
  );
}
