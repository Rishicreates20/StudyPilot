import { cn } from "cn";
import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

type EmptyStateProps = {
  title: string;
  description?: string;
  icon?: LucideIcon;
  /** Usually a primary call to action, so an empty screen always offers a next step. */
  action?: ReactNode;
  /** Heading level to use so the state fits the surrounding outline. */
  headingLevel?: "h2" | "h3" | "h4";
  className?: string;
};

export function EmptyState({
  title,
  description,
  icon: Icon,
  action,
  headingLevel: Heading = "h3",
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center gap-3 rounded-xl border border-dashed bg-card/50 px-6 py-12 text-center",
        className,
      )}
    >
      {Icon ? (
        <div className="flex size-12 items-center justify-center rounded-full bg-secondary text-secondary-foreground">
          <Icon className="size-6" aria-hidden="true" />
        </div>
      ) : null}
      <Heading className="text-base font-semibold tracking-tight">{title}</Heading>
      {description ? <p className="max-w-md text-sm text-muted-foreground">{description}</p> : null}
      {action ? <div className="pt-2">{action}</div> : null}
    </div>
  );
}
