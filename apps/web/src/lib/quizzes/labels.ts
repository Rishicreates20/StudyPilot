import type { BadgeVariant } from "@/components/ui/badge";
import type { AnswerResult, GenerationJob, MasteryBand, QuestionOut } from "@/lib/api/server";

/** What the learner is told while a quiz job moves through the worker's stages. */
const QUIZ_STAGE_TEXT: Readonly<Record<string, string>> = {
  queued: "Waiting for a free worker…",
  starting: "Getting started…",
  loading: "Reading your lesson…",
  writing: "Writing your questions…",
  validated: "Checking the questions…",
  saving: "Saving your quiz…",
  waiting_retry: "The AI service was busy. Trying again shortly…",
};

export function describeQuizStage(job: Pick<GenerationJob, "stage" | "status">): string {
  if (job.status === "queued" && job.stage === "queued") return QUIZ_STAGE_TEXT["queued"] ?? "";
  return QUIZ_STAGE_TEXT[job.stage] ?? "Working on it…";
}

/** The same for a grading job (marking short answers). */
const GRADE_STAGE_TEXT: Readonly<Record<string, string>> = {
  queued: "Waiting for a free worker…",
  starting: "Getting started…",
  loading: "Reading your answers…",
  grading: "Comparing your answers with the rubric…",
  validated: "Checking the marking…",
  saving: "Saving your result…",
  waiting_retry: "The AI service was busy. Trying again shortly…",
};

export function describeGradingStage(job: Pick<GenerationJob, "stage" | "status">): string {
  if (job.status === "queued" && job.stage === "queued") return GRADE_STAGE_TEXT["queued"] ?? "";
  return GRADE_STAGE_TEXT[job.stage] ?? "Working on it…";
}

const BAND_LABELS: Readonly<Record<MasteryBand, string>> = {
  needs_practice: "Needs practice",
  progressing: "Getting there",
  mastered: "Mastered",
};

const BAND_VARIANTS: Readonly<Record<MasteryBand, BadgeVariant>> = {
  needs_practice: "warning",
  progressing: "info",
  mastered: "success",
};

export const bandLabel = (band: MasteryBand): string => BAND_LABELS[band];
export const bandVariant = (band: MasteryBand): BadgeVariant => BAND_VARIANTS[band];

/** The one-line meaning of a band, with the thresholds that decided it. */
export function bandExplanation(
  band: MasteryBand,
  thresholds: { needs_practice_below: number; mastered_from: number },
): string {
  const low = Math.round(thresholds.needs_practice_below);
  const high = Math.round(thresholds.mastered_from);
  switch (band) {
    case "needs_practice":
      return `Below ${low}%: worth another go at the parts that scored lowest.`;
    case "progressing":
      return `Between ${low}% and ${high}%: you have the basics and a little more practice will firm them up.`;
    case "mastered":
      return `${high}% or more: you know this topic well.`;
  }
}

/** "62%": scores are shown as whole percentages. */
export function formatPercent(value: number): string {
  return `${Math.round(value)}%`;
}

const KIND_LABELS: Readonly<Record<QuestionOut["kind"], string>> = {
  multiple_choice: "Multiple choice",
  true_false: "True or false",
  short_answer: "Short answer",
};

export const kindLabel = (kind: QuestionOut["kind"]): string => KIND_LABELS[kind];

const DIFFICULTY_LABELS: Readonly<Record<QuestionOut["difficulty"], string>> = {
  easy: "Easy",
  medium: "Medium",
  hard: "Hard",
};

export const difficultyLabel = (difficulty: QuestionOut["difficulty"]): string =>
  DIFFICULTY_LABELS[difficulty];

/** How many points a question is worth, for a screen reader and for the page. */
export function pointsLabel(points: number): string {
  return points === 1 ? "1 point" : `${points} points`;
}

const METHOD_LABELS: Readonly<Record<AnswerResult["grading_method"], string>> = {
  deterministic: "Marked automatically",
  ai_estimate: "AI estimate",
  self_review: "Marked by you",
  pending: "Waiting to be marked",
};

export const gradingMethodLabel = (method: AnswerResult["grading_method"]): string =>
  METHOD_LABELS[method];

/** Shown wherever a model's marking of free text appears. */
export const ESTIMATE_NOTE =
  "An AI compared your answer with the rubric above. It is an estimate and can be wrong: use the model answer to check it, and mark it yourself if you disagree.";

/** Points with at most one decimal: "2", "1.5". */
export function formatPoints(points: number): string {
  return Number.isInteger(points) ? String(points) : points.toFixed(1);
}
