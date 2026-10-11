import type { GenerationJob, Roadmap } from "@/lib/api/server";

/** What the learner is told while a job moves through the worker's stages. */
const STAGE_TEXT: Readonly<Record<string, string>> = {
  queued: "Waiting for a free worker…",
  starting: "Getting started…",
  loading: "Reading your goal…",
  planning: "Planning your roadmap…",
  validated: "Checking the plan against your schedule…",
  saving: "Saving your roadmap…",
  waiting_retry: "The AI service was busy. Trying again shortly…",
};

export function describeStage(job: Pick<GenerationJob, "stage" | "status">): string {
  if (job.status === "queued" && job.stage === "queued") return STAGE_TEXT["queued"] ?? "";
  return STAGE_TEXT[job.stage] ?? "Working on it…";
}

/** "45 min", "1 h", "2 h 15 min". */
export function formatMinutes(minutes: number): string {
  const whole = Math.max(0, Math.round(minutes));
  if (whole < 60) return `${whole} min`;
  const hours = Math.floor(whole / 60);
  const rest = whole % 60;
  return rest === 0 ? `${hours} h` : `${hours} h ${rest} min`;
}

export function pluralize(count: number, singular: string, plural = `${singular}s`): string {
  return `${count} ${count === 1 ? singular : plural}`;
}

/**
 * Where a plan's content comes from, in words that never overstate it. Only a plan built from the
 * learner's own uploaded material may say so; everything else says it is not an official syllabus.
 */
export function syllabusBasisNote(basis: Roadmap["syllabus_basis"]): string {
  switch (basis) {
    case "uploaded_document":
      return "Built from the material you uploaded.";
    case "learner_stated":
      return "Built from what you told us about your goal. It is not an official syllabus.";
    case "general_knowledge":
      return "Built from general knowledge of the subject. It is not an official syllabus.";
  }
}

export function itemKindLabel(kind: "topic" | "revision" | "enrichment"): string {
  return { topic: "Topic", revision: "Revision", enrichment: "Optional" }[kind];
}
