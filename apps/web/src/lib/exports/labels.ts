import type {
  Export,
  ExportFormat,
  ExportStatus,
  LessonExportFormat,
  RoadmapExportFormat,
} from "@/lib/api/server";

/** What each format is, in the learner's words. */
export const FORMAT_LABELS: Readonly<Record<ExportFormat, { title: string; detail: string }>> = {
  notes_pdf: {
    title: "Study notes (PDF)",
    detail: "The whole lesson, ready to print or read offline.",
  },
  revision_pdf: {
    title: "Revision sheet (PDF)",
    detail: "Key points, terms, mistakes to avoid and a checklist on one or two pages.",
  },
  roadmap_pdf: { title: "Roadmap (PDF)", detail: "The plan with its day-by-day schedule." },
  slides_pptx: {
    title: "Slides (PowerPoint)",
    detail: "A deck to present or revise from, with the details in the speaker notes.",
  },
};

export const LESSON_FORMATS: readonly LessonExportFormat[] = [
  "notes_pdf",
  "revision_pdf",
  "slides_pptx",
];
export const ROADMAP_FORMATS: readonly RoadmapExportFormat[] = ["roadmap_pdf", "slides_pptx"];

export const STATUS_LABELS: Readonly<Record<ExportStatus, string>> = {
  ready: "Ready to download",
  processing: "Being made",
  failed: "Couldn't be made",
  not_started: "Not made yet",
};

export function isLessonFormat(value: unknown): value is LessonExportFormat {
  return typeof value === "string" && (LESSON_FORMATS as readonly string[]).includes(value);
}

export function isRoadmapFormat(value: unknown): value is RoadmapExportFormat {
  return typeof value === "string" && (ROADMAP_FORMATS as readonly string[]).includes(value);
}

export { formatBytes } from "@/lib/documents/labels";

const STAGES: Readonly<Record<string, string>> = {
  queued: "Waiting to start",
  starting: "Starting",
  loading: "Getting the content",
  rendering: "Laying out the file",
  uploading: "Saving the file",
  saving: "Finishing",
  waiting_retry: "Waiting to try again",
};

/** Where a job making a file is, in words (unknown stages are described generically). */
export function describeExportStage(stage: string): string {
  return STAGES[stage] ?? "Working";
}

/** "12 pages", "1 slide". */
export function pagesLabel(item: Pick<Export, "format" | "page_count">): string | null {
  if (item.page_count == null) return null;
  const unit = item.format === "slides_pptx" ? "slide" : "page";
  return `${item.page_count} ${unit}${item.page_count === 1 ? "" : "s"}`;
}

/** Whether any export is still being made (the list then refreshes itself). */
export function anyProcessing(items: readonly Pick<Export, "status">[]): boolean {
  return items.some((item) => item.status === "processing");
}
