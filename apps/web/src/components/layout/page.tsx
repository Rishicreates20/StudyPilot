import { cn } from "cn";
import type { ReactNode } from "react";

/** Consistent horizontal page width and gutters. */
export function PageContainer({
  className,
  children,
}: {
  className?: string;
  children: ReactNode;
}) {
  return (
    <div className={cn("mx-auto w-full max-w-6xl px-4 sm:px-6 lg:px-8", className)}>{children}</div>
  );
}

type PageHeaderProps = {
  title: string;
  description?: string;
  eyebrow?: ReactNode;
  actions?: ReactNode;
  className?: string;
};

/** The single `<h1>` of a page, with optional eyebrow, description and actions. */
export function PageHeader({ title, description, eyebrow, actions, className }: PageHeaderProps) {
  return (
    <div
      className={cn("flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between", className)}
    >
      <div className="max-w-2xl space-y-3">
        {eyebrow ? <div>{eyebrow}</div> : null}
        <h1 className="font-heading text-3xl font-semibold tracking-tight sm:text-4xl">{title}</h1>
        {description ? <p className="text-base text-muted-foreground">{description}</p> : null}
      </div>
      {actions ? <div className="flex shrink-0 flex-wrap gap-2">{actions}</div> : null}
    </div>
  );
}
