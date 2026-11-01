import type { GenerationJob, TopicVideos } from "@/lib/api/server";

export type VideoCardState = {
  /** A search waiting or running now (shown with live progress). */
  active: GenerationJob | null;
  /** The newest search failed, and it is newer than the suggestions shown (if any). */
  failed: GenerationJob | null;
  /** Whether "Find videos" / "Find other videos" can be offered right now. */
  canSearch: boolean;
};

/** What the videos card shows, from what the API returned. */
export function videoCardState(data: TopicVideos): VideoCardState {
  const job = data.job;
  const active = job && (job.status === "queued" || job.status === "running") ? job : null;
  const failed =
    job?.status === "failed" &&
    (data.search === null || Date.parse(job.created_at) > Date.parse(data.search.searched_at))
      ? job
      : null;
  return { active, failed, canSearch: data.can_search && active === null };
}
