import * as React from "react";
import { cn } from "cn";

function Textarea({ className, ...props }: React.ComponentProps<"textarea">) {
  return (
    <textarea
      data-slot="textarea"
      className={cn(
        // text-base on small screens avoids iOS zooming into focused fields.
        "min-h-24 w-full min-w-0 rounded-lg border border-input bg-card px-3 py-2 text-base shadow-xs transition-colors outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-destructive aria-invalid:focus-visible:ring-destructive md:text-sm",
        className,
      )}
      {...props}
    />
  );
}

export { Textarea };
