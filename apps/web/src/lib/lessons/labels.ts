import type { GenerationJob, ItemStudy, LessonAdjust } from "@/lib/api/server";

/** What the learner is told while a lesson job moves through the worker's stages. */
const STAGE_TEXT: Readonly<Record<string, string>> = {
  queued: "Waiting for a free worker…",
  starting: "Getting started…",
  loading: "Reading your roadmap…",
  writing: "Writing your lesson…",
  validated: "Checking the lesson…",
  saving: "Saving your lesson…",
  waiting_retry: "The AI service was busy. Trying again shortly…",
};

export function describeLessonStage(job: Pick<GenerationJob, "stage" | "status">): string {
  if (job.status === "queued" && job.stage === "queued") return STAGE_TEXT["queued"] ?? "";
  return STAGE_TEXT[job.stage] ?? "Working on it…";
}

export const ADJUST_OPTIONS: readonly {
  readonly value: LessonAdjust;
  readonly label: string;
  readonly hint: string;
}[] = [
  {
    value: "simpler",
    label: "Simpler",
    hint: "Plainer words, shorter sentences and more everyday comparisons.",
  },
  {
    value: "more_examples",
    label: "More examples",
    hint: "More worked examples and concrete cases.",
  },
  {
    value: "deeper",
    label: "Go deeper",
    hint: "More detail, edge cases and the reasoning behind the rules.",
  },
];

export function adjustLabel(adjust: LessonAdjust | null): string | null {
  return ADJUST_OPTIONS.find((option) => option.value === adjust)?.label ?? null;
}

export function isLessonAdjust(value: unknown): value is LessonAdjust {
  return ADJUST_OPTIONS.some((option) => option.value === value);
}

const STUDY_STATUS: Readonly<Record<ItemStudy["status"], string>> = {
  not_started: "Not started",
  in_progress: "In progress",
  completed: "Done",
};

export function studyStatusLabel(status: ItemStudy["status"]): string {
  return STUDY_STATUS[status];
}

/** "Not started", "2 of 5 sections", or "Done": a short line for lists of topics. */
export function studySummary(study: ItemStudy): string {
  if (study.status === "completed") return "Done";
  if (study.status === "in_progress" && study.sections_total > 0) {
    return `${study.sections_done} of ${study.sections_total} sections`;
  }
  return study.has_lesson ? "Lesson ready" : "Not started";
}

/** The text of a study button on a roadmap topic. */
export function studyActionLabel(study: ItemStudy): string {
  if (study.status === "completed") return "Review";
  if (study.status === "in_progress") return "Continue";
  return study.has_lesson ? "Start studying" : "Open lesson";
}
