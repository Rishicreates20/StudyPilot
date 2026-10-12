import type {
  DocumentList,
  DocumentPage,
  DocumentPages,
  GenerationJob,
  StudyDocument,
} from "@/lib/api/server";
import { GOAL, lessonJob } from "@/test-support/lessons";

export { GOAL };
export const DOC = "99999999-9999-4999-8999-999999999999";
export const DOC_JOB = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";

export function documentJob(overrides: Partial<GenerationJob> = {}): GenerationJob {
  return lessonJob({
    id: DOC_JOB,
    job_type: "document",
    item_id: null,
    document_id: DOC,
    stage: "extracting",
    progress: 30,
    ...overrides,
  });
}

export function studyDocument(overrides: Partial<StudyDocument> = {}): StudyDocument {
  return {
    id: DOC,
    goal_id: GOAL,
    title: "Rust notes",
    kind: "pdf",
    original_name: "rust.pdf",
    size_bytes: 20_480,
    status: "ready",
    error_code: null,
    error_message: null,
    paginated: true,
    page_count: 3,
    chunk_count: 7,
    char_count: 4_000,
    ocr_page_count: 0,
    warnings: [],
    embedding_model: "gemini-embedding-001",
    indexed_at: "2026-10-11T10:05:00Z",
    created_at: "2026-10-11T10:00:00Z",
    updated_at: "2026-10-11T10:05:00Z",
    job: documentJob({ status: "completed", stage: "done", progress: 100 }),
    needs_review: false,
    ...overrides,
  };
}

export function documentList(
  items: StudyDocument[] = [studyDocument()],
  overrides: Partial<DocumentList> = {},
): DocumentList {
  return {
    items,
    limits: {
      max_bytes: 10 * 1024 * 1024,
      max_pages: 300,
      max_ocr_pages: 20,
      documents_per_goal: 20,
      accepted: ["PDF", "Plain text (.txt, .md)", "Images (.png, .jpg, .webp)", "Pasted text"],
    },
    goal_archived: false,
    storage_available: true,
    ocr_available: true,
    indexing_available: true,
    ...overrides,
  };
}

export function documentPage(overrides: Partial<DocumentPage> = {}): DocumentPage {
  return {
    page_number: 1,
    text: "Ownership means each value has one owner.",
    source: "text_layer",
    legibility: null,
    needs_review: false,
    edited: false,
    ...overrides,
  };
}

export function documentPages(
  items: DocumentPage[] = [documentPage()],
  overrides: Partial<DocumentPages> = {},
): DocumentPages {
  return { items, total: items.length, offset: 0, limit: 20, editable: false, ...overrides };
}
