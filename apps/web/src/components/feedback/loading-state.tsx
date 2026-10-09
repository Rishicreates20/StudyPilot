import { cn } from "cn";
import { LoaderCircleIcon } from "lucide-react";

import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

/** A spinner with a visible, announced label. Use for short waits where layout is unknown. */
export function LoadingState({
  label = "Loading",
  className,
}: {
  label?: string;
  className?: string;
}) {
  return (
    <div
      role="status"
      className={cn(
        "flex items-center justify-center gap-3 py-10 text-sm text-muted-foreground",
        className,
      )}
    >
      <LoaderCircleIcon
        className="size-5 animate-spin motion-reduce:animate-none"
        aria-hidden="true"
      />
      <span>{label}…</span>
    </div>
  );
}

/**
 * Skeleton placeholders for a grid of cards. The decorative blocks are hidden from assistive
 * technology; a single live region announces the wait instead.
 */
export function CardGridSkeleton({
  count = 3,
  label = "Loading",
  className,
}: {
  count?: number;
  label?: string;
  className?: string;
}) {
  return (
    <div role="status" aria-busy="true" className={className}>
      <span className="sr-only">{label}…</span>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: count }, (_, index) => (
          <Card key={index}>
            <CardHeader>
              <Skeleton className="h-5 w-2/3" />
              <Skeleton className="h-4 w-full" />
            </CardHeader>
            <CardContent className="space-y-2">
              <Skeleton className="h-4 w-1/2" />
              <Skeleton className="h-2 w-full rounded-full" />
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
