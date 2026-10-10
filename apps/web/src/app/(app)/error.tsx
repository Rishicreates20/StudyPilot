"use client";

import { useEffect } from "react";

import { ErrorState } from "@/components/feedback/error-state";
import { PageContainer } from "@/components/layout/page";

/** Unexpected failures inside the signed-in area: a calm message and a retry, never a stack trace. */
export default function AppError({
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
    <PageContainer className="py-10">
      <ErrorState
        title="We couldn't load this page"
        description="Your data is safe. Try again, and if it keeps happening let us know."
        reference={error.digest}
        onRetry={retry}
      />
    </PageContainer>
  );
}
