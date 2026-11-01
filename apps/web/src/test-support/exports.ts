import type { Export, GenerationJob } from "@/lib/api/server";
import { GOAL, LESSON, lessonJob } from "@/test-support/lessons";

export { GOAL, LESSON };
export const EXPORT = "66666666-6666-4666-8666-666666666666";
export const ROADMAP = "77777777-7777-4777-8777-777777777777";
export const EXPORT_JOB = "88888888-8888-4888-8888-888888888888";

export function exportJob(overrides: Partial<GenerationJob> = {}): GenerationJob {
  return lessonJob({
    id: EXPORT_JOB,
    job_type: "export",
    item_id: null,
    export_id: EXPORT,
    stage: "rendering",
    progress: 35,
    ...overrides,
  });
}

/** A ready PDF of a lesson's notes; override for other formats, sources and states. */
export function exportItem(overrides: Partial<Export> = {}): Export {
  return {
    id: EXPORT,
    goal_id: GOAL,
    lesson_id: LESSON,
    roadmap_id: null,
    source_title: "Ownership in Rust",
    source_version: 2,
    format: "notes_pdf",
    template_version: "v1",
    status: "ready",
    file_name: "ownership-in-rust-notes.pdf",
    content_type: "application/pdf",
    size_bytes: 20_480,
    page_count: 3,
    unsupported_characters: 0,
    ready_at: "2026-10-11T10:05:00Z",
    created_at: "2026-10-11T10:00:00Z",
    job: exportJob({ status: "completed", stage: "done", progress: 100 }),
    ...overrides,
  };
}
