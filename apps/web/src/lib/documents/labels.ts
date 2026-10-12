import type { DocumentKind, DocumentStatus, GenerationJob, StudyDocument } from "@/lib/api/server";

/** What the learner is told while a document job moves through the worker's stages. */
const STAGE_TEXT: Readonly<Record<string, string>> = {
  queued: "Waiting for a free worker…",
  starting: "Getting started…",
  loading: "Opening your document…",
  reading: "Fetching the file…",
  extracting: "Reading the text…",
  reading_pages: "Reading the scanned pages…",
  saving_pages: "Saving the text…",
  chunking: "Splitting it into passages…",
  embedding: "Indexing the passages…",
  waiting_rate_limit: "The AI service asked us to slow down. Waiting a moment…",
  saving: "Saving the index…",
  waiting_retry: "The AI service was busy. Trying again shortly…",
};

export function describeDocumentStage(job: Pick<GenerationJob, "stage" | "status">): string {
  if (job.status === "queued" && job.stage === "queued") return STAGE_TEXT["queued"] ?? "";
  return STAGE_TEXT[job.stage] ?? "Working on it…";
}

const STATUS_LABEL: Readonly<Record<DocumentStatus, string>> = {
  queued: "Waiting",
  processing: "Processing",
  review: "Check the text",
  ready: "Ready",
  failed: "Couldn't process",
};

export function documentStatusLabel(status: DocumentStatus): string {
  return STATUS_LABEL[status];
}

const KIND_LABEL: Readonly<Record<DocumentKind, string>> = {
  pdf: "PDF",
  text: "Text file",
  image: "Picture",
  pasted: "Pasted text",
};

export function documentKindLabel(kind: DocumentKind): string {
  return KIND_LABEL[kind];
}

/** "1.2 MB", "340 KB", "12 bytes". */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} ${bytes === 1 ? "byte" : "bytes"}`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function pluralize(count: number, singular: string, plural = `${singular}s`): string {
  return `${count} ${count === 1 ? singular : plural}`;
}

/** What a document's size is made of, in a few words: "3 pages · 12 passages". */
export function documentSummary(document: StudyDocument): string {
  const parts: string[] = [];
  if (document.page_count) {
    parts.push(pluralize(document.page_count, document.paginated ? "page" : "part"));
  }
  if (document.chunk_count > 0) parts.push(pluralize(document.chunk_count, "passage"));
  return parts.join(" · ");
}

/** "Page 3" for a real page of a PDF or picture, "Part 3" for a stretch of a text. */
export function pageLabel(paginated: boolean, number: number): string {
  return `${paginated ? "Page" : "Part"} ${number}`;
}

export function legibilityLabel(legibility: string | null): string | null {
  switch (legibility) {
    case "clear":
      return "Read clearly";
    case "partly":
      return "Partly unclear";
    case "poor":
      return "Hard to read";
    case "none":
      return "Unreadable";
    default:
      return null;
  }
}
