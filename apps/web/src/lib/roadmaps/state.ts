import type { GenerationJob, RoadmapSummary } from "@/lib/api/server";

/** What the goal page shows in its roadmap section. */
export type RoadmapPanelState =
  | { kind: "generating"; job: GenerationJob }
  | { kind: "failed"; job: GenerationJob; current: RoadmapSummary | null }
  | { kind: "ready"; current: RoadmapSummary; versions: number }
  | { kind: "none" };

const ACTIVE = new Set<GenerationJob["status"]>(["queued", "running"]);

/**
 * Decides the roadmap section from the goal's newest job and its roadmap versions.
 *
 * - a job in progress always wins: the learner is waiting for it;
 * - a failed newest job is shown (with a retry) until a newer roadmap exists, so a failure is
 *   never hidden behind an older plan the learner did not just ask for;
 * - otherwise the current roadmap, or the invitation to make one.
 *
 * `jobs` is newest first, as the API returns it.
 */
export function roadmapPanelState(
  jobs: readonly GenerationJob[],
  versions: readonly RoadmapSummary[],
): RoadmapPanelState {
  const latest = jobs[0];
  const current = versions.find((version) => version.status === "current") ?? null;

  if (latest && ACTIVE.has(latest.status)) return { kind: "generating", job: latest };
  if (latest?.status === "failed") {
    const newestRoadmap = versions.reduce<number | null>((newest, version) => {
      const made = Date.parse(version.created_at);
      return newest === null || made > newest ? made : newest;
    }, null);
    if (newestRoadmap === null || Date.parse(latest.created_at) > newestRoadmap) {
      return { kind: "failed", job: latest, current };
    }
  }
  if (current) return { kind: "ready", current, versions: versions.length };
  return { kind: "none" };
}
