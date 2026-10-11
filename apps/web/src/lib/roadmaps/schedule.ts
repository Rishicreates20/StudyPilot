import type { Roadmap, RoadmapItem } from "@/lib/api/server";

export type ScheduledDay = {
  day: number;
  minutes: number;
  items: RoadmapItem[];
};

/**
 * The plan laid out day by day: every scheduled topic and revision session grouped under its day
 * number, in study order. Optional enrichment is not scheduled and is left out.
 */
export function scheduleByDay(
  roadmap: Pick<Roadmap, "modules" | "revision_sessions">,
): ScheduledDay[] {
  const scheduled = [
    ...roadmap.modules.flatMap((module) => module.topics),
    ...roadmap.revision_sessions,
  ].filter((item) => item.day_number !== null);

  const days = new Map<number, ScheduledDay>();
  for (const item of scheduled) {
    const day = item.day_number as number;
    const entry = days.get(day) ?? { day, minutes: 0, items: [] };
    entry.items.push(item);
    entry.minutes += item.estimated_minutes;
    days.set(day, entry);
  }
  return [...days.values()]
    .map((entry) => ({ ...entry, items: entry.items.toSorted((a, b) => a.position - b.position) }))
    .toSorted((a, b) => a.day - b.day);
}

/** Titles of the items a given item depends on, in plan order, for "Needs: …" lines. */
export function prerequisiteTitles(
  item: Pick<RoadmapItem, "prerequisite_ids">,
  allItems: readonly Pick<RoadmapItem, "id" | "title" | "position">[],
): string[] {
  const wanted = new Set(item.prerequisite_ids);
  return allItems
    .filter((candidate) => wanted.has(candidate.id))
    .toSorted((a, b) => a.position - b.position)
    .map((candidate) => candidate.title);
}

export function allTopics(roadmap: Pick<Roadmap, "modules">): RoadmapItem[] {
  return roadmap.modules.flatMap((module) => module.topics);
}
