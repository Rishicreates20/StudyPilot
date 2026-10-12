import type { GenerationJob, StudyDocument } from "@/lib/api/server";

/** What a document's panel shows. */
export type DocumentPanelState =
  /** Being read or indexed right now (or waiting for a worker): live progress. */
  | { kind: "working"; job: GenerationJob }
  /** Text was read from a picture and waits for the learner to check it before it is used. */
  | { kind: "review" }
  /** Indexed: it can be searched and cited. */
  | { kind: "ready" }
  /** Could not be processed; `message` says why in words a learner can act on. */
  | { kind: "failed"; message: string }
  /** The job was stopped and the document is still waiting; processing it again starts afresh. */
  | { kind: "stopped" };

const ACTIVE = new Set<GenerationJob["status"]>(["queued", "running"]);

/**
 * Decides the panel from the document's status and its newest job.
 *
 * A document is `queued` or `processing` while the worker holds it, so an active job means
 * "working". If the job has ended without the document moving on (cancelled, or failed and the
 * worker's reaper has not marked the document yet) the learner is told so instead of waiting for
 * progress that will never come.
 */
export function documentPanelState(
  document: Pick<StudyDocument, "status" | "error_message" | "job">,
): DocumentPanelState {
  const { job } = document;
  switch (document.status) {
    case "ready":
      return { kind: "ready" };
    case "review":
      return job && ACTIVE.has(job.status) ? { kind: "working", job } : { kind: "review" };
    case "failed":
      return {
        kind: "failed",
        message: document.error_message ?? "This document couldn't be processed.",
      };
    case "queued":
    case "processing":
      if (job && ACTIVE.has(job.status)) return { kind: "working", job };
      if (job?.status === "failed") {
        return {
          kind: "failed",
          message: job.error_message ?? "This document couldn't be processed.",
        };
      }
      return { kind: "stopped" };
  }
}

/** Whether any of the documents is still being worked on (so the page should keep refreshing). */
export function anyWorking(documents: readonly Pick<StudyDocument, "status" | "job">[]): boolean {
  return documents.some(
    (document) =>
      (document.status === "queued" ||
        document.status === "processing" ||
        document.status === "review") &&
      document.job !== null &&
      document.job !== undefined &&
      ACTIVE.has(document.job.status),
  );
}
