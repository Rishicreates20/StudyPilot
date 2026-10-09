import { cn } from "cn";

/** Decorative placeholder; pair it with a labelled live region (see `LoadingState`). */
function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="skeleton"
      aria-hidden="true"
      className={cn("animate-pulse rounded-md bg-accent motion-reduce:animate-none", className)}
      {...props}
    />
  );
}

export { Skeleton };
