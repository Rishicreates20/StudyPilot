import type {
  GenerationJob,
  ItemStudy,
  LessonDetail,
  LessonDocument,
  OutlineEntry,
  ProgressState,
  StudyView,
} from "@/lib/api/server";

export const GOAL = "11111111-1111-4111-8111-111111111111";
export const ITEM = "22222222-2222-4222-8222-222222222222";
export const NEXT_ITEM = "33333333-3333-4333-8333-333333333333";
export const LESSON = "44444444-4444-4444-8444-444444444444";
export const JOB = "55555555-5555-4555-8555-555555555555";

export function study(overrides: Partial<ItemStudy> = {}): ItemStudy {
  return {
    status: "not_started",
    has_lesson: false,
    sections_done: 0,
    sections_total: 0,
    ...overrides,
  };
}

export function document(overrides: Partial<LessonDocument> = {}): LessonDocument {
  return {
    language: "en",
    title: "Ownership in Rust",
    learning_objectives: ["Explain what ownership means", "Predict when a value is dropped"],
    sections: [
      {
        id: "s1",
        heading: "What ownership is",
        blocks: [
          { type: "paragraph", text: "Every value has **one owner** at a time, called `owner`." },
          { type: "list", ordered: false, items: ["It moves", "It is dropped"] },
          { type: "code", language: "rust", code: "let a = String::new();", caption: "A value" },
          { type: "callout", kind: "tip", title: "Remember", text: "Think of a single key." },
        ],
      },
      {
        id: "s2",
        heading: "Borrowing",
        blocks: [
          { type: "paragraph", text: "A reference lets you look without taking." },
          { type: "list", ordered: true, items: ["Take a reference", "Use it"] },
          { type: "callout", kind: "warning", text: "You cannot mutate while borrowed." },
        ],
      },
      {
        id: "s3",
        heading: "Putting it together",
        blocks: [{ type: "callout", kind: "note", text: "A short recap of the rules." }],
      },
    ],
    definitions: [{ term: "Owner", meaning: "The variable responsible for a value." }],
    worked_examples: [
      {
        title: "Moving a string",
        problem: "What happens when you assign a String to another variable?",
        steps: ["The value moves.", "The old name is invalid."],
        answer: "Only the new name can be used.",
      },
    ],
    common_misconceptions: [
      { misconception: "Assignment always copies.", correction: "For String it moves." },
    ],
    summary: ["One owner at a time.", "Borrowing lets others look."],
    simple_explanation: {
      paragraphs: ["Think of a toy that only one child can hold at a time."],
      analogy: "Like a library book with one borrower.",
    },
    source_references: [],
    ...overrides,
  };
}

export function lesson(overrides: Partial<LessonDetail> = {}): LessonDetail {
  const content = overrides.content ?? document();
  return {
    id: LESSON,
    item_id: ITEM,
    version: 1,
    status: "current",
    title: content.title,
    adjust: null,
    is_synthetic: false,
    created_at: "2026-10-11T10:00:00Z",
    language: "en",
    content,
    content_version: 1,
    revision_feedback: null,
    based_on_lesson_id: null,
    prompt_version: "lesson-writer/v1",
    provider: "gemini",
    model_id: "gemini-3.6-flash",
    ...overrides,
  };
}

export function progress(overrides: Partial<ProgressState> = {}): ProgressState {
  return {
    lesson_id: LESSON,
    status: "in_progress",
    completed_section_ids: [],
    current_section_id: null,
    started_at: "2026-10-11T10:05:00Z",
    last_studied_at: "2026-10-11T10:06:00Z",
    completed_at: null,
    ...overrides,
  };
}

export function lessonJob(overrides: Partial<GenerationJob> = {}): GenerationJob {
  return {
    id: JOB,
    goal_id: GOAL,
    item_id: ITEM,
    job_type: "lesson",
    status: "running",
    stage: "writing",
    progress: 20,
    attempts: 1,
    max_attempts: 3,
    cancel_requested: false,
    error_code: null,
    error_message: null,
    roadmap_id: null,
    lesson_id: null,
    attempt_id: null,
    quiz_id: null,
    created_at: "2026-10-11T10:00:00Z",
    started_at: "2026-10-11T10:00:01Z",
    finished_at: null,
    ...overrides,
  };
}

export function outline(): OutlineEntry[] {
  return [
    {
      item_id: ITEM,
      key: "ownership",
      title: "Ownership",
      kind: "topic",
      module_title: "Core ideas",
      estimated_minutes: 30,
      study: study({
        status: "in_progress",
        has_lesson: true,
        sections_done: 1,
        sections_total: 3,
      }),
    },
    {
      item_id: NEXT_ITEM,
      key: "borrowing",
      title: "Borrowing",
      kind: "topic",
      module_title: "Core ideas",
      estimated_minutes: 30,
      study: study(),
    },
    {
      item_id: "66666666-6666-4666-8666-666666666666",
      key: "extra",
      title: "Optional extra",
      kind: "enrichment",
      module_title: null,
      estimated_minutes: 20,
      study: study({ status: "completed", has_lesson: true, sections_done: 3, sections_total: 3 }),
    },
  ];
}

export function studyView(overrides: Partial<StudyView> = {}): StudyView {
  return {
    topic: {
      id: ITEM,
      goal_id: GOAL,
      roadmap_id: "77777777-7777-4777-8777-777777777777",
      key: "ownership",
      kind: "topic",
      title: "Ownership",
      description: "How Rust manages memory.",
      practice_task: "Write a function that borrows a string.",
      estimated_minutes: 30,
      day_number: 1,
      module_title: "Core ideas",
    },
    roadmap: {
      id: "77777777-7777-4777-8777-777777777777",
      version: 1,
      status: "current",
      title: "Learn Rust",
    },
    lesson: null,
    versions: [],
    progress: null,
    job: null,
    previous: null,
    next: { id: NEXT_ITEM, title: "Borrowing" },
    outline: outline(),
    goal_archived: false,
    can_generate: true,
    ...overrides,
  };
}
