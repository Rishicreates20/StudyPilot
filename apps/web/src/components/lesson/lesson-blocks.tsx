import { cn } from "cn";
import { AlertTriangleIcon, InfoIcon, LightbulbIcon, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import type { LessonBlock } from "@/lib/api/server";
import { parseInline } from "@/lib/lessons/inline";

/** A piece of lesson text with its `code` and **bold** parts, as ordinary React nodes. */
export function Inline({ text }: { text: string }) {
  return (
    <>
      {parseInline(text).map((part, index) => {
        if (part.kind === "code") {
          return (
            <code
              key={index}
              className="rounded bg-muted px-1.5 py-0.5 font-mono text-[0.9em] break-words"
            >
              {part.text}
            </code>
          );
        }
        if (part.kind === "strong") return <strong key={index}>{part.text}</strong>;
        return <span key={index}>{part.text}</span>;
      })}
    </>
  );
}

const CALLOUTS: Readonly<
  Record<
    "tip" | "note" | "warning",
    { icon: LucideIcon; label: string; className: string; iconClassName: string }
  >
> = {
  tip: {
    icon: LightbulbIcon,
    label: "Tip",
    className: "border-success/30 bg-success-soft text-success-foreground",
    iconClassName: "text-success",
  },
  note: {
    icon: InfoIcon,
    label: "Note",
    className: "border-info/30 bg-info-soft text-info-foreground",
    iconClassName: "text-info",
  },
  warning: {
    icon: AlertTriangleIcon,
    label: "Watch out",
    className: "border-warning/40 bg-warning-soft text-warning-foreground",
    iconClassName: "text-warning",
  },
};

/**
 * One block of a lesson. Every block type is rendered from its typed fields; there is no path from
 * lesson text to HTML. Callouts are a labelled `note`, not a live region: they are part of the
 * reading, and must not interrupt a screen reader the way an error does.
 */
export function Block({ block }: { block: LessonBlock }): ReactNode {
  switch (block.type) {
    case "paragraph":
      return (
        <p className="leading-7">
          <Inline text={block.text} />
        </p>
      );
    case "list": {
      const Tag = block.ordered ? "ol" : "ul";
      return (
        <Tag
          className={cn("space-y-2 pl-6 leading-7", block.ordered ? "list-decimal" : "list-disc")}
        >
          {block.items.map((item, index) => (
            <li key={index} className="pl-1">
              <Inline text={item} />
            </li>
          ))}
        </Tag>
      );
    }
    case "code":
      return (
        <figure className="space-y-2">
          <div className="overflow-hidden rounded-lg border bg-muted/60">
            <div className="flex items-center justify-between border-b bg-muted px-3 py-1.5 text-xs text-muted-foreground">
              <span className="font-mono">{block.language}</span>
            </div>
            {/* Focusable so a keyboard user can scroll a long line sideways. */}
            <pre
              tabIndex={0}
              aria-label={`Code example in ${block.language}`}
              className="overflow-x-auto p-4 font-mono text-sm leading-6 outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
            >
              <code>{block.code}</code>
            </pre>
          </div>
          {block.caption ? (
            <figcaption className="text-sm text-muted-foreground">{block.caption}</figcaption>
          ) : null}
        </figure>
      );
    case "callout": {
      const style = CALLOUTS[block.kind];
      const Icon = style.icon;
      return (
        <div
          role="note"
          aria-label={block.title ?? style.label}
          className={cn("flex gap-3 rounded-lg border p-4 text-sm leading-6", style.className)}
        >
          <Icon className={cn("mt-0.5 size-4 shrink-0", style.iconClassName)} aria-hidden="true" />
          <div className="space-y-1">
            <p className="font-medium">{block.title ?? style.label}</p>
            <p>
              <Inline text={block.text} />
            </p>
          </div>
        </div>
      );
    }
  }
}
