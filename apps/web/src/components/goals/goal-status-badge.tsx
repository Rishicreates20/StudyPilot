import { Badge, type BadgeVariant } from "@/components/ui/badge";
import type { GoalStatus } from "@/lib/api/server";

const STATUS_BADGES: Record<GoalStatus, { label: string; variant: BadgeVariant }> = {
  active: { label: "Active", variant: "info" },
  paused: { label: "Paused", variant: "warning" },
  completed: { label: "Completed", variant: "success" },
  archived: { label: "Archived", variant: "secondary" },
};

/** The state of a goal as a coloured label. The word, not just the colour, carries the meaning. */
export function GoalStatusBadge({ status }: { status: GoalStatus }) {
  const { label, variant } = STATUS_BADGES[status];
  return <Badge variant={variant}>{label}</Badge>;
}
