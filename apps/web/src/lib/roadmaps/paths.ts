import { goalPath } from "@/lib/goals/ids";

/** The roadmap page of a goal: its current version, or a specific one (`version` is a number). */
export function roadmapPath(goalId: string, version?: number): string {
  const base = `${goalPath(goalId)}/roadmap`;
  return version === undefined ? base : `${base}?version=${version}`;
}

/** Parses `?version=2`; anything that is not a positive whole number means "the current one". */
export function parseVersion(value: string | undefined): number | undefined {
  if (value === undefined || !/^[1-9][0-9]{0,5}$/.test(value)) return undefined;
  return Number(value);
}
