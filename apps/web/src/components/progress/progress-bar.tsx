import { cn } from "cn";
import { useId } from "react";

import { Progress } from "@/components/ui/progress";

type ProgressBarProps = {
  /** Visible label that also names the progress bar for assistive technology. */
  label: string;
  value: number;
  max?: number;
  /** Hide the percentage text (the bar still exposes its value to assistive technology). */
  showValue?: boolean;
  description?: string;
  className?: string;
};

export function percentOf(value: number, max: number) {
  if (!Number.isFinite(value) || !Number.isFinite(max) || max <= 0) return 0;
  return Math.round(Math.min(1, Math.max(0, value / max)) * 100);
}

/** A labelled progress indicator, for example lesson or roadmap completion. */
export function ProgressBar({
  label,
  value,
  max = 100,
  showValue = true,
  description,
  className,
}: ProgressBarProps) {
  const labelId = useId();
  const percent = percentOf(value, max);

  return (
    <div className={cn("space-y-2", className)}>
      <div className="flex items-baseline justify-between gap-4 text-sm">
        <span id={labelId} className="font-medium">
          {label}
        </span>
        {showValue ? (
          <span className="text-muted-foreground tabular-nums" aria-hidden="true">
            {percent}%
          </span>
        ) : null}
      </div>
      <Progress value={percent} aria-labelledby={labelId} aria-valuetext={`${percent}%`} />
      {description ? <p className="text-xs text-muted-foreground">{description}</p> : null}
    </div>
  );
}
