import { cn } from "cn";
import type { ReactNode } from "react";

import { percentOf } from "@/components/progress/progress-bar";

type ProgressRingProps = {
  /** Accessible name, for example "Kubernetes mastery". */
  label: string;
  value: number;
  max?: number;
  /** Diameter in pixels. */
  size?: number;
  strokeWidth?: number;
  /** Content drawn in the centre; defaults to the percentage. */
  children?: ReactNode;
  className?: string;
};

/** Circular progress, suited to mastery scores and daily goals. */
export function ProgressRing({
  label,
  value,
  max = 100,
  size = 96,
  strokeWidth = 8,
  children,
  className,
}: ProgressRingProps) {
  const percent = percentOf(value, max);
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference * (1 - percent / 100);

  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={percent}
      aria-valuetext={`${percent}%`}
      className={cn("relative inline-flex items-center justify-center", className)}
      style={{ width: size, height: size }}
    >
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        className="-rotate-90"
        aria-hidden="true"
      >
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={strokeWidth}
          className="stroke-secondary"
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          className="stroke-primary transition-[stroke-dashoffset] duration-500 ease-out motion-reduce:transition-none"
        />
      </svg>
      <span className="absolute text-lg font-semibold tabular-nums" aria-hidden="true">
        {children ?? `${percent}%`}
      </span>
    </div>
  );
}
