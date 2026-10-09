import { cn } from "cn";

/** The StudyPilot mark: a paper plane on a rounded tile. Decorative; pair it with text. */
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 32 32"
      fill="none"
      aria-hidden="true"
      focusable="false"
      className={cn("size-8 shrink-0", className)}
    >
      <rect width="32" height="32" rx="9" className="fill-primary" />
      <path d="M7.5 15.2 24.5 7.5 17 24.5l-2.6-6.9-6.9-2.4Z" className="fill-primary-foreground" />
      <path
        d="m14.4 17.6 5.2-5.2"
        className="stroke-primary"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
    </svg>
  );
}

export function Logo({ name, className }: { name: string; className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <LogoMark />
      <span className="font-heading text-lg font-semibold tracking-tight">{name}</span>
    </span>
  );
}
