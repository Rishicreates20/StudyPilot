"use client";

import {
  ArrowRightIcon,
  CheckIcon,
  FlaskConicalIcon,
  ListIcon,
  SparklesIcon,
  Undo2Icon,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { Block, Inline } from "@/components/lesson/lesson-blocks";
import { LessonContents } from "@/components/lesson/lesson-contents";
import {
  KeyTerms,
  Misconceptions,
  SimpleExplanationCard,
  Sources,
  SummaryList,
  WorkedExamples,
} from "@/components/lesson/lesson-extras";
import { TopicNavigation } from "@/components/lesson/topic-navigation";
import { ProgressBar } from "@/components/progress/progress-bar";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import type { LessonDetail, NeighbourTopic, OutlineEntry, ProgressState } from "@/lib/api/server";
import { adjustLabel } from "@/lib/lessons/labels";
import { saveProgressAction } from "@/lib/lessons/actions";
import { studyPath } from "@/lib/lessons/paths";
import { resumeSectionId } from "@/lib/lessons/state";

/** How long after the learner stops to wait before saving where they are. */
export const SAVE_AFTER_READING_MS = 1_500;
/** Where the "reading line" is, as a fraction of the screen's height from the top. */
const READING_LINE = 0.3;
/** How long after ticking a section to wait before saving (lets a few ticks batch together). */
export const SAVE_AFTER_TICK_MS = 400;

type Snapshot = {
  done: ReadonlySet<string>;
  finished: boolean;
  current: string | null;
};

type SaveState =
  | { status: "idle" }
  | { status: "saving" }
  | { status: "saved" }
  | { status: "error"; reason: "session" | "archived" | "unavailable" };

type LessonReaderProps = {
  goalId: string;
  itemId: string;
  lesson: LessonDetail;
  progress: ProgressState | null;
  outline: readonly OutlineEntry[];
  previous: NeighbourTopic | null;
  next: NeighbourTopic | null;
  /** The goal is archived: the lesson can be read but nothing is saved. */
  readOnly: boolean;
  /** Controls for a new version (server-rendered forms), shown next to "Explain simply". */
  versionActions: ReactNode;
};

/**
 * The study workspace for one lesson: the lesson itself, a contents panel, the learner's progress
 * and the "Explain simply" action.
 *
 * Progress is saved through a Server Action as the learner reads (which section they are in) and
 * as they tick sections off, a moment after each change; the access token never reaches the
 * browser. Reopening the lesson scrolls back to the saved section. If a save fails the learner
 * is told and can retry; reading is never blocked.
 */
export function LessonReader({
  goalId,
  itemId,
  lesson,
  progress,
  outline,
  previous,
  next,
  readOnly,
  versionActions,
}: LessonReaderProps) {
  const { content } = lesson;
  const sections = content.sections;
  const sectionIds = useMemo(() => sections.map((section) => section.id), [sections]);
  const lastSectionId = sectionIds.at(-1) ?? null;

  const [done, setDone] = useState<ReadonlySet<string>>(
    () => new Set(progress?.completed_section_ids ?? []),
  );
  const [finished, setFinished] = useState(progress?.status === "completed");
  const [current, setCurrent] = useState<string | null>(progress?.current_section_id ?? null);
  const [simple, setSimple] = useState(false);
  const [save, setSave] = useState<SaveState>({ status: "idle" });
  const [resumeDismissed, setResumeDismissed] = useState(false);
  const [contentsOpen, setContentsOpen] = useState(false);

  const latest = useRef<Snapshot>({ done, finished, current });
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const persist = useCallback(async () => {
    if (readOnly) return;
    if (timer.current) {
      clearTimeout(timer.current);
      timer.current = null;
    }
    const snapshot = latest.current;
    setSave({ status: "saving" });
    try {
      const result = await saveProgressAction(goalId, itemId, lesson.id, {
        completedSectionIds: sectionIds.filter((id) => snapshot.done.has(id)),
        currentSectionId: snapshot.current,
        completed: snapshot.finished,
      });
      setSave(result.ok ? { status: "saved" } : { status: "error", reason: result.reason });
    } catch {
      setSave({ status: "error", reason: "unavailable" });
    }
  }, [goalId, itemId, lesson.id, readOnly, sectionIds]);

  /** Record a change in the reader's state and save it after `delay` ms. */
  const change = useCallback(
    (patch: Partial<Snapshot>, delay: number) => {
      latest.current = { ...latest.current, ...patch };
      if (patch.done) setDone(patch.done);
      if (patch.finished !== undefined) setFinished(patch.finished);
      if (patch.current !== undefined) setCurrent(patch.current);
      if (readOnly) return;
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => void persist(), delay);
    },
    [persist, readOnly],
  );

  // Save what is pending when the learner leaves the tab or the lesson.
  useEffect(() => {
    const flush = () => {
      if (timer.current) void persist();
    };
    const onVisibility = () => {
      if (document.visibilityState === "hidden") flush();
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      flush();
    };
  }, [persist]);

  // Follow the learner's reading position: the last section whose top has reached the "reading
  // line" near the top of the screen. Measured on scroll, so a jump straight to the end counts too.
  useEffect(() => {
    const onScroll = () => {
      const line = window.innerHeight * READING_LINE;
      let reading: string | null = null;
      for (const id of sectionIds) {
        const top = document.getElementById(id)?.getBoundingClientRect().top;
        if (top !== undefined && top <= line) reading = id;
      }
      if (reading && reading !== latest.current.current) {
        change({ current: reading }, SAVE_AFTER_READING_MS);
      }
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [sectionIds, change]);

  // Reopening a lesson: go back to where the learner was (unless the link names a place).
  const resumeId = useMemo(() => resumeSectionId(sectionIds, progress), [sectionIds, progress]);
  const resumeHeading = sections.find((section) => section.id === resumeId)?.heading ?? null;
  useEffect(() => {
    if (!resumeId || window.location.hash) return;
    document.getElementById(resumeId)?.scrollIntoView({ block: "start" });
  }, [resumeId]);

  function toggleSection(id: string) {
    const nextDone = new Set(latest.current.done);
    const ticking = !nextDone.has(id);
    if (ticking) nextDone.add(id);
    else nextDone.delete(id);
    // Finishing a section means the learner is there: that is where to pick up again.
    change(
      { done: nextDone, finished: false, ...(ticking ? { current: id } : {}) },
      SAVE_AFTER_TICK_MS,
    );
  }

  function finishLesson() {
    change({ done: new Set(sectionIds), finished: true, current: lastSectionId }, 0);
  }

  const total = sectionIds.length;
  const doneCount = sectionIds.filter((id) => done.has(id)).length;
  const contents = (idPrefix: string, onNavigate?: () => void) => (
    <LessonContents
      goalId={goalId}
      sections={sections}
      doneIds={done}
      currentId={current}
      outline={outline}
      currentItemId={itemId}
      idPrefix={idPrefix}
      onNavigate={onNavigate}
    />
  );

  return (
    <div className="lg:grid lg:grid-cols-[17rem_minmax(0,1fr)] lg:gap-10">
      <aside className="hidden lg:block" aria-label="Contents">
        <div className="sticky top-20 max-h-[calc(100vh-6rem)] space-y-6 overflow-y-auto pr-2 pb-6">
          <ProgressBar
            label="Your progress"
            value={doneCount}
            max={total}
            description={finished ? "Lesson finished" : `${doneCount} of ${total} sections done`}
          />
          {contents("side")}
        </div>
      </aside>

      <div className="min-w-0 space-y-8">
        {/* Small screens: progress and the contents sheet stay within reach. */}
        <div className="sticky top-16 z-30 -mx-4 flex items-center gap-3 border-b bg-background/95 px-4 py-2.5 backdrop-blur sm:-mx-6 sm:px-6 lg:hidden">
          <div className="min-w-0 flex-1 space-y-1">
            <p className="text-xs text-muted-foreground">
              {finished ? "Lesson finished" : `${doneCount} of ${total} sections done`}
            </p>
            <Progress
              value={total === 0 ? 0 : Math.round((doneCount / total) * 100)}
              aria-label="Lesson progress"
              className="h-1.5"
            />
          </div>
          <Sheet open={contentsOpen} onOpenChange={setContentsOpen}>
            <SheetTrigger asChild>
              <Button variant="outline" size="sm">
                <ListIcon aria-hidden="true" />
                Contents
              </Button>
            </SheetTrigger>
            <SheetContent side="left">
              <SheetHeader>
                <SheetTitle>Contents</SheetTitle>
                <SheetDescription>
                  The sections of this lesson and the topics of your roadmap.
                </SheetDescription>
              </SheetHeader>
              <div className="overflow-y-auto px-4 pb-6">
                {contents("sheet", () => setContentsOpen(false))}
              </div>
            </SheetContent>
          </Sheet>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            variant={simple ? "default" : "outline"}
            aria-pressed={simple}
            onClick={() => setSimple((value) => !value)}
          >
            <SparklesIcon aria-hidden="true" />
            {simple ? "Hide the simple explanation" : "Explain simply"}
          </Button>
          {versionActions}
          <p
            role="status"
            aria-live="polite"
            className="ml-auto text-xs text-muted-foreground"
            data-testid="save-status"
          >
            {readOnly
              ? "Read-only: this goal is archived."
              : save.status === "saving"
                ? "Saving…"
                : save.status === "saved"
                  ? "Progress saved"
                  : ""}
          </p>
        </div>

        {save.status === "error" ? (
          <Alert variant="warning">
            <AlertTitle>Your progress wasn&rsquo;t saved</AlertTitle>
            <AlertDescription>
              <p>
                {save.reason === "session"
                  ? "Your session has ended. Sign in again to keep your place."
                  : save.reason === "archived"
                    ? "This goal is archived, so its lessons are read-only."
                    : "The learning service couldn't be reached. You can keep reading."}
              </p>
              {save.reason === "unavailable" ? (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="mt-3"
                  onClick={() => void persist()}
                >
                  Try saving again
                </Button>
              ) : null}
            </AlertDescription>
          </Alert>
        ) : null}

        {resumeId && resumeHeading && !resumeDismissed ? (
          <Alert variant="info">
            <AlertTitle>Welcome back</AlertTitle>
            <AlertDescription>
              <p>
                You left off at <span className="font-medium">{resumeHeading}</span>.
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                <Button
                  type="button"
                  size="sm"
                  onClick={() => {
                    document.getElementById(resumeId)?.scrollIntoView({ block: "start" });
                    setResumeDismissed(true);
                  }}
                >
                  Continue there
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    window.scrollTo({ top: 0 });
                    setResumeDismissed(true);
                  }}
                >
                  Start from the top
                </Button>
              </div>
            </AlertDescription>
          </Alert>
        ) : null}

        <article className="max-w-prose space-y-10 text-base" aria-label={content.title}>
          {simple ? <SimpleExplanationCard explanation={content.simple_explanation} /> : null}

          <section aria-labelledby="objectives" className="space-y-3">
            <h2 id="objectives" className="font-heading text-xl font-semibold tracking-tight">
              What you will learn
            </h2>
            <ul className="list-disc space-y-2 pl-6 leading-7">
              {content.learning_objectives.map((objective, index) => (
                <li key={index} className="pl-1">
                  <Inline text={objective} />
                </li>
              ))}
            </ul>
          </section>

          {sections.map((section) => {
            const isDone = done.has(section.id);
            return (
              <section
                key={section.id}
                id={section.id}
                aria-labelledby={`${section.id}-heading`}
                className="space-y-4"
              >
                <h2
                  id={`${section.id}-heading`}
                  className="font-heading text-2xl font-semibold tracking-tight"
                >
                  {section.heading}
                </h2>
                {section.blocks.map((block, index) => (
                  <Block key={index} block={block} />
                ))}
                {readOnly ? null : (
                  <Button
                    type="button"
                    size="sm"
                    variant={isDone ? "secondary" : "outline"}
                    aria-pressed={isDone}
                    onClick={() => toggleSection(section.id)}
                  >
                    {isDone ? <Undo2Icon aria-hidden="true" /> : <CheckIcon aria-hidden="true" />}
                    {isDone ? "Done: undo" : "Mark section as done"}{" "}
                    <span className="sr-only">for {section.heading}</span>
                  </Button>
                )}
              </section>
            );
          })}

          <KeyTerms definitions={content.definitions} />
          <WorkedExamples examples={content.worked_examples} />
          <Misconceptions items={content.common_misconceptions} />
          <SummaryList summary={content.summary} />

          {readOnly ? null : (
            <section
              aria-labelledby="finish-heading"
              className="space-y-3 rounded-xl border bg-card p-5"
            >
              <h2 id="finish-heading" className="font-heading text-lg font-semibold">
                {finished ? "Lesson complete" : "Finished reading?"}
              </h2>
              {finished ? (
                <div className="space-y-3">
                  <p className="text-sm text-muted-foreground">
                    Well done. Every section is marked as done.
                    {lesson.status === "current" ? "" : " (This is an earlier version.)"}
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {next ? (
                      <Button asChild>
                        <Link href={studyPath(goalId, next.id)}>
                          Next topic: {next.title}
                          <ArrowRightIcon aria-hidden="true" />
                        </Link>
                      </Button>
                    ) : null}
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => change({ finished: false }, 0)}
                    >
                      Mark as not finished
                    </Button>
                  </div>
                </div>
              ) : (
                <div className="space-y-3">
                  <p className="text-sm text-muted-foreground">
                    Marks every section as done. You can come back to this lesson at any time.
                  </p>
                  <Button type="button" onClick={finishLesson}>
                    <CheckIcon aria-hidden="true" />
                    Finish lesson
                  </Button>
                </div>
              )}
            </section>
          )}

          <Sources references={content.source_references} />

          <footer className="space-y-2 border-t pt-4 text-xs text-muted-foreground">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="secondary">Version {lesson.version}</Badge>
              {lesson.status === "superseded" ? (
                <Badge variant="outline">Earlier version</Badge>
              ) : null}
              {adjustLabel(lesson.adjust) ? (
                <Badge variant="outline">{adjustLabel(lesson.adjust)}</Badge>
              ) : null}
              {lesson.is_synthetic ? (
                <Badge variant="warning">
                  <FlaskConicalIcon aria-hidden="true" />
                  Sample lesson
                </Badge>
              ) : null}
            </div>
            <p>
              {lesson.is_synthetic
                ? "Written by the built-in test provider, not an AI model."
                : `Written by an AI model (${lesson.model_id}) and checked by our software for structure; it has not been reviewed by a person.`}{" "}
              Prompt {lesson.prompt_version}.
            </p>
          </footer>
        </article>

        <TopicNavigation goalId={goalId} previous={previous} next={next} />
      </div>
    </div>
  );
}
