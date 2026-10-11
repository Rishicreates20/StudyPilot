import { GOAL_STATUS_OPTIONS } from "@/lib/goals/options";
import type { GoalStatus } from "@/lib/api/server";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * Whether `value` looks like a goal ID. Values that arrive from the browser (a URL segment, an
 * argument bound into a Server Action) are checked before they are put into an API path, so a
 * crafted value such as "../me" can never change which endpoint is called.
 */
export function isGoalId(value: unknown): value is string {
  return typeof value === "string" && UUID.test(value);
}

export function isGoalStatus(value: unknown): value is GoalStatus {
  return GOAL_STATUS_OPTIONS.some((option) => option.value === value);
}

export const goalPath = (goalId: string) => `/goals/${goalId}`;
export const editGoalPath = (goalId: string) => `/goals/${goalId}/edit`;
