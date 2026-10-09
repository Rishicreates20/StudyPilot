import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "cn";

const alertVariants = cva(
  "group/alert relative grid w-full gap-0.5 rounded-lg border px-4 py-3 text-left text-sm has-data-[slot=alert-action]:pr-24 has-[>svg]:grid-cols-[auto_1fr] has-[>svg]:gap-x-3 *:[svg]:row-span-2 *:[svg]:translate-y-0.5 *:[svg]:text-current *:[svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        default: "bg-card text-card-foreground",
        info: "border-info/30 bg-info-soft text-info-foreground *:data-[slot=alert-description]:text-inherit",
        success:
          "border-success/30 bg-success-soft text-success-foreground *:data-[slot=alert-description]:text-inherit",
        warning:
          "border-warning/40 bg-warning-soft text-warning-foreground *:data-[slot=alert-description]:text-inherit",
        destructive:
          "border-destructive/30 bg-destructive-soft text-destructive-foreground *:data-[slot=alert-description]:text-inherit",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

type AlertVariant = NonNullable<VariantProps<typeof alertVariants>["variant"]>;

/** Problems interrupt assistive technology; informational messages are announced politely. */
const INTERRUPTING_VARIANTS: ReadonlySet<AlertVariant> = new Set(["warning", "destructive"]);

function Alert({
  className,
  variant = "default",
  ...props
}: React.ComponentProps<"div"> & VariantProps<typeof alertVariants>) {
  const resolved: AlertVariant = variant ?? "default";
  return (
    <div
      data-slot="alert"
      role={INTERRUPTING_VARIANTS.has(resolved) ? "alert" : "status"}
      className={cn(alertVariants({ variant: resolved }), className)}
      {...props}
    />
  );
}

function AlertTitle({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="alert-title"
      className={cn(
        "font-medium group-has-[>svg]/alert:col-start-2 [&_a]:underline [&_a]:underline-offset-3",
        className,
      )}
      {...props}
    />
  );
}

function AlertDescription({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="alert-description"
      className={cn(
        "text-sm text-muted-foreground group-has-[>svg]/alert:col-start-2 [&_a]:underline [&_a]:underline-offset-3 [&_p:not(:last-child)]:mb-4",
        className,
      )}
      {...props}
    />
  );
}

function AlertAction({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div data-slot="alert-action" className={cn("absolute top-3 right-3", className)} {...props} />
  );
}

export { Alert, AlertTitle, AlertDescription, AlertAction, alertVariants };
export type { AlertVariant };
