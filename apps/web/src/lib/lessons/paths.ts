import { goalPath } from "@/lib/goals/ids";

/**
 * The study page of a roadmap topic. `lessonId` opens an earlier version of its lesson instead of
 * the current one.
 */
export function studyPath(goalId: string, itemId: string, lessonId?: string): string {
  const base = `${goalPath(goalId)}/learn/${itemId}`;
  return lessonId === undefined ? base : `${base}?lesson=${lessonId}`;
}
