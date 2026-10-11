import type {
  GenerationJob,
  LessonDetail,
  ProgressState,
  RoadmapItem,
  StudyView,
} from "@/lib/api/server";

/** What the study page shows for a topic. */
export type StudyPanelState =
  /** No lesson yet and one is being written. */
  | { kind: "generating"; job: GenerationJob }
  /** No lesson, and the last attempt failed. */
  | { kind: "failed"; job: GenerationJob }
  /** A lesson to study; `writing` / `failedNewer` describe a new version in flight or that failed. */
  | {
      kind: "ready";
      lesson: LessonDetail;
      writing: GenerationJob | null;
      failedNewer: GenerationJob | null;
    }
  /** Nothing yet: offer to write the lesson. */
  | { kind: "empty" };

const ACTIVE = new Set<GenerationJob["status"]>(["queued", "running"]);

/**
 * Decides the study page from the topic's newest lesson job and the lesson being shown.
 *
 * - with no lesson, a job in progress wins (the learner is waiting for it), then a failure (with a
 *   retry), then the invitation to write one;
 * - with a lesson, it is always shown: a new version being written, or one that failed after this
 *   lesson was made, is reported next to it rather than in place of it.
 */
export function studyPanelState(view: Pick<StudyView, "job" | "lesson">): StudyPanelState {
  const { job, lesson } = view;
  const active = job && ACTIVE.has(job.status) ? job : null;

  if (!lesson) {
    if (active) return { kind: "generating", job: active };
    if (job?.status === "failed") return { kind: "failed", job };
    return { kind: "empty" };
  }
  const failedNewer =
    job?.status === "failed" && Date.parse(job.created_at) > Date.parse(lesson.created_at)
      ? job
      : null;
  return { kind: "ready", lesson, writing: active, failedNewer };
}

export type LessonProgressSummary = {
  done: number;
  total: number;
  percent: number;
  completed: boolean;
};

/** How far through a lesson the learner is, from the saved progress. */
export function summarizeProgress(
  sectionIds: readonly string[],
  progress: Pick<ProgressState, "completed_section_ids" | "status"> | null,
): LessonProgressSummary {
  const total = sectionIds.length;
  const known = new Set(sectionIds);
  const done = progress ? progress.completed_section_ids.filter((id) => known.has(id)).length : 0;
  return {
    done,
    total,
    percent: total === 0 ? 0 : Math.round((done / total) * 100),
    completed: progress?.status === "completed",
  };
}

/**
 * The section to scroll to when the lesson is reopened: the saved place if it still names a
 * section of this lesson, otherwise none (start at the top).
 */
export function resumeSectionId(
  sectionIds: readonly string[],
  progress: Pick<ProgressState, "current_section_id" | "status"> | null,
): string | null {
  if (!progress || progress.status === "completed") return null;
  const id = progress.current_section_id;
  if (id === null || id === sectionIds[0]) return null;
  return sectionIds.includes(id) ? id : null;
}

/**
 * Where "Continue studying" should lead: the topic the learner is part-way through, otherwise the
 * first topic they have not finished. `topics` are in study order. Null when every topic is done.
 */
export function continueTarget(topics: readonly RoadmapItem[]): RoadmapItem | null {
  return (
    topics.find((topic) => topic.study.status === "in_progress") ??
    topics.find((topic) => topic.study.status !== "completed") ??
    null
  );
}
