import { cn } from "cn";
import { CheckCircle2Icon, CircleDotIcon, CircleIcon } from "lucide-react";
import Link from "next/link";

import type { OutlineEntry } from "@/lib/api/server";
import { studySummary } from "@/lib/lessons/labels";
import { studyPath } from "@/lib/lessons/paths";

type SectionRef = { readonly id: string; readonly heading: string };

type LessonContentsProps = {
  goalId: string;
  sections: readonly SectionRef[];
  doneIds: ReadonlySet<string>;
  currentId: string | null;
  outline: readonly OutlineEntry[];
  currentItemId: string;
  /** Keeps element ids unique when the contents appear twice (beside the lesson and in a sheet). */
  idPrefix: string;
  /** Called when a link is followed (the mobile sheet closes itself). */
  onNavigate?: () => void;
};

function StateIcon({ done, current }: { done: boolean; current: boolean }) {
  if (done) {
    return <CheckCircle2Icon className="mt-0.5 size-4 shrink-0 text-success" aria-hidden="true" />;
  }
  if (current) {
    return <CircleDotIcon className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden="true" />;
  }
  return <CircleIcon className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden="true" />;
}

/** The topics of the roadmap, grouped by module, in study order. */
function groupByModule(outline: readonly OutlineEntry[]) {
  const groups: { title: string; entries: OutlineEntry[] }[] = [];
  for (const entry of outline) {
    const title = entry.module_title ?? "Optional extras";
    const last = groups.at(-1);
    if (last && last.title === title) last.entries.push(entry);
    else groups.push({ title, entries: [entry] });
  }
  return groups;
}

/**
 * The contents of the study workspace: the sections of this lesson (with the learner's place and
 * what they have finished) and every topic of the roadmap. Shown beside the lesson on large
 * screens and in a sheet on small ones. State is conveyed by an icon AND by text for assistive
 * technology, never by colour alone.
 */
export function LessonContents({
  goalId,
  sections,
  doneIds,
  currentId,
  outline,
  currentItemId,
  idPrefix,
  onNavigate,
}: LessonContentsProps) {
  return (
    <div className="space-y-8">
      <nav aria-labelledby={`${idPrefix}-sections-heading`}>
        <h2
          id={`${idPrefix}-sections-heading`}
          className="mb-3 text-xs font-semibold tracking-wide text-muted-foreground uppercase"
        >
          In this lesson
        </h2>
        <ol className="space-y-1">
          {sections.map((section) => {
            const done = doneIds.has(section.id);
            const current = currentId === section.id;
            return (
              <li key={section.id}>
                <a
                  href={`#${section.id}`}
                  onClick={onNavigate}
                  aria-current={current ? "location" : undefined}
                  className={cn(
                    "flex gap-2 rounded-md px-2 py-1.5 text-sm outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring",
                    current && "bg-accent font-medium",
                  )}
                >
                  <StateIcon done={done} current={current} />
                  <span>
                    {section.heading}
                    {done ? (
                      <>
                        {" "}
                        <span className="sr-only">(done)</span>
                      </>
                    ) : null}
                  </span>
                </a>
              </li>
            );
          })}
        </ol>
      </nav>

      <nav aria-labelledby={`${idPrefix}-topics-heading`}>
        <h2
          id={`${idPrefix}-topics-heading`}
          className="mb-3 text-xs font-semibold tracking-wide text-muted-foreground uppercase"
        >
          Roadmap topics
        </h2>
        <div className="space-y-4">
          {groupByModule(outline).map((group) => (
            <div key={group.title}>
              <h3 className="mb-1 px-2 text-sm font-medium">{group.title}</h3>
              <ol className="space-y-0.5">
                {group.entries.map((entry) => {
                  const here = entry.item_id === currentItemId;
                  return (
                    <li key={entry.item_id}>
                      <Link
                        href={studyPath(goalId, entry.item_id)}
                        onClick={onNavigate}
                        aria-current={here ? "page" : undefined}
                        className={cn(
                          "flex gap-2 rounded-md px-2 py-1.5 text-sm outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring",
                          here && "bg-accent font-medium",
                        )}
                      >
                        <StateIcon done={entry.study.status === "completed"} current={here} />
                        <span className="min-w-0">
                          <span className="block">{entry.title}</span>
                          <span className="block text-xs font-normal text-muted-foreground">
                            {studySummary(entry.study)}
                          </span>
                        </span>
                      </Link>
                    </li>
                  );
                })}
              </ol>
            </div>
          ))}
        </div>
      </nav>
    </div>
  );
}
