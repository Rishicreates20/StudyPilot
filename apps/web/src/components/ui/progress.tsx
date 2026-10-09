"use client";

import * as React from "react";
import { cn } from "cn";
import { Progress as ProgressPrimitive } from "radix-ui";

type ProgressProps = React.ComponentProps<typeof ProgressPrimitive.Root>;

/**
 * Low-level progress track. Pass `value` as 0-100; omit it (or pass null) for an
 * indeterminate state. Prefer `ProgressBar`, which adds a visible label and value text.
 */
function Progress({ className, value, ...props }: ProgressProps) {
  const determinate = typeof value === "number";
  const clamped = determinate ? Math.min(100, Math.max(0, value)) : 0;
  return (
    <ProgressPrimitive.Root
      data-slot="progress"
      value={determinate ? clamped : null}
      className={cn("relative h-2 w-full overflow-hidden rounded-full bg-secondary", className)}
      {...props}
    >
      <ProgressPrimitive.Indicator
        data-slot="progress-indicator"
        className={cn(
          "h-full rounded-full bg-primary transition-[width] duration-300 ease-out",
          !determinate && "w-1/3 animate-pulse motion-reduce:animate-none",
        )}
        style={determinate ? { width: `${clamped}%` } : undefined}
      />
    </ProgressPrimitive.Root>
  );
}

export { Progress };
