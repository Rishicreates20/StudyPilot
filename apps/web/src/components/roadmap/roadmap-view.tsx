import {
  CalendarDaysIcon,
  CircleAlertIcon,
  ClockIcon,
  FlaskConicalIcon,
  InfoIcon,
  ListChecksIcon,
  TargetIcon,
  TimerIcon,
} from "lucide-react";
import type { ReactNode } from "react";

import { StatCard } from "@/components/goals/stat-card";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { Roadmap, RoadmapItem } from "@/lib/api/server";
import { formatDate } from "@/lib/format";
import { formatMinutes, pluralize, syllabusBasisNote } from "@/lib/roadmaps/labels";
import { allTopics, prerequisiteTitles, scheduleByDay } from "@/lib/roadmaps/schedule";

/**
 * A stored roadmap, read-only. Every number shown (topics, minutes, days) was computed by the
 * server from the stored items; nothing here is the model's own claim about its plan.
 */
export function RoadmapView({ roadmap }: { roadmap: Roadmap }) {
  const topics = allTopics(roadmap);
  const everyItem: RoadmapItem[] = [...topics, ...roadmap.revision_sessions];
  const objectiveNumber = new Map(roadmap.objectives.map((o, index) => [o.id, index + 1]));
  const days = scheduleByDay(roadmap);

  return (
    <div className="space-y-10">
      {roadmap.is_synthetic ? (
        <Alert variant="warning">
          <FlaskConicalIcon aria-hidden="true" />
          <AlertTitle>Sample plan</AlertTitle>
          <AlertDescription>
            This roadmap came from the built-in test provider, not an AI model. It only shows how a
            roadmap looks.
          </AlertDescription>
        </Alert>
      ) : null}

      <section aria-labelledby="overview-heading" className="space-y-4">
        <h2 id="overview-heading" className="font-heading text-xl font-semibold tracking-tight">
          Overview
        </h2>
        <p className="text-base leading-relaxed">{roadmap.overview}</p>
        <div className="flex gap-3 rounded-lg border bg-card p-4 text-sm">
          <TargetIcon className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden="true" />
          <p>
            <span className="font-medium">Target outcome: </span>
            {roadmap.target_outcome}
          </p>
        </div>
        <p className="flex items-start gap-2 text-sm text-muted-foreground">
          <InfoIcon className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
          {syllabusBasisNote(roadmap.syllabus_basis)}
        </p>
      </section>

      <section aria-label="Plan at a glance" className="grid gap-4 sm:grid-cols-2">
        <StatCard label="Topics" value={roadmap.topic_count} icon={ListChecksIcon} />
        <StatCard
          label="Study time"
          value={formatMinutes(roadmap.total_minutes)}
          icon={ClockIcon}
        />
        <StatCard
          label="Duration"
          value={pluralize(roadmap.total_days, "day")}
          icon={CalendarDaysIcon}
          hint={
            roadmap.target_date ? `Target: ${formatDate(roadmap.target_date)}` : "No target date"
          }
        />
        <StatCard
          label="Planned for"
          value={`${roadmap.daily_minutes} min / day`}
          icon={TimerIcon}
        />
      </section>

      {roadmap.unknowns.length > 0 ? (
        <Alert variant="warning">
          <CircleAlertIcon aria-hidden="true" />
          <AlertTitle>Please check these yourself</AlertTitle>
          <AlertDescription>
            <ul className="list-disc space-y-1 pl-5">
              {roadmap.unknowns.map((unknown) => (
                <li key={unknown}>{unknown}</li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      ) : null}

      {roadmap.assumptions.length > 0 ? (
        <Alert variant="info">
          <InfoIcon aria-hidden="true" />
          <AlertTitle>What this plan assumes</AlertTitle>
          <AlertDescription>
            <ul className="list-disc space-y-1 pl-5">
              {roadmap.assumptions.map((assumption) => (
                <li key={assumption}>{assumption}</li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      ) : null}

      <section aria-labelledby="objectives-heading" className="space-y-3">
        <h2 id="objectives-heading" className="font-heading text-xl font-semibold tracking-tight">
          By the end you will be able to
        </h2>
        <ol className="space-y-2">
          {roadmap.objectives.map((objective, index) => (
            <li key={objective.id} className="flex gap-3 text-sm">
              <span
                className="flex size-6 shrink-0 items-center justify-center rounded-full bg-secondary text-xs font-semibold tabular-nums"
                aria-hidden="true"
              >
                {index + 1}
              </span>
              <span>
                <span className="sr-only">Objective {index + 1}: </span>
                {objective.text}
              </span>
            </li>
          ))}
        </ol>
      </section>

      <section aria-labelledby="modules-heading" className="space-y-4">
        <h2 id="modules-heading" className="font-heading text-xl font-semibold tracking-tight">
          Modules and topics
        </h2>
        {roadmap.modules.map((module) => (
          <Card key={module.id}>
            <CardHeader>
              <CardTitle className="text-lg">
                <h3>
                  Module {module.position}: {module.title}
                </h3>
              </CardTitle>
              <CardDescription>{module.summary}</CardDescription>
            </CardHeader>
            <CardContent>
              <ol className="space-y-3">
                {module.topics.map((topic) => (
                  <ItemCard
                    key={topic.id}
                    item={topic}
                    footer={footerFor(topic, everyItem, objectiveNumber)}
                  />
                ))}
              </ol>
            </CardContent>
          </Card>
        ))}
      </section>

      {roadmap.revision_sessions.length > 0 ? (
        <section aria-labelledby="revision-heading" className="space-y-4">
          <h2 id="revision-heading" className="font-heading text-xl font-semibold tracking-tight">
            Revision sessions
          </h2>
          <ol className="space-y-3">
            {roadmap.revision_sessions.map((session) => (
              <ItemCard
                key={session.id}
                item={session}
                footer={
                  session.prerequisite_ids.length > 0
                    ? `Revisits: ${prerequisiteTitles(session, everyItem).join(", ")}`
                    : null
                }
              />
            ))}
          </ol>
        </section>
      ) : null}

      {roadmap.enrichment.length > 0 ? (
        <section aria-labelledby="enrichment-heading" className="space-y-4">
          <h2 id="enrichment-heading" className="font-heading text-xl font-semibold tracking-tight">
            Optional extras
          </h2>
          <p className="text-sm text-muted-foreground">
            These are not scheduled and are not part of the study time above.
          </p>
          <ul className="space-y-3">
            {roadmap.enrichment.map((extra) => (
              <ItemCard key={extra.id} item={extra} footer={null} />
            ))}
          </ul>
        </section>
      ) : null}

      <details className="group rounded-lg border bg-card">
        <summary className="cursor-pointer rounded-lg px-4 py-3 text-sm font-medium outline-none focus-visible:ring-2 focus-visible:ring-ring">
          Day-by-day schedule ({pluralize(days.length, "study day")})
        </summary>
        <ol className="space-y-4 border-t px-4 py-4">
          {days.map((day) => (
            <li key={day.day}>
              <p className="text-sm font-medium">
                Day {day.day}{" "}
                <span className="font-normal text-muted-foreground">
                  · {formatMinutes(day.minutes)}
                </span>
              </p>
              <ul className="mt-1 list-disc space-y-0.5 pl-5 text-sm text-muted-foreground">
                {day.items.map((item) => (
                  <li key={item.id}>
                    {item.kind === "revision" ? "Revise: " : ""}
                    {item.title} ({formatMinutes(item.estimated_minutes)})
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ol>
      </details>
    </div>
  );
}

function footerFor(
  topic: RoadmapItem,
  everyItem: readonly RoadmapItem[],
  objectiveNumber: ReadonlyMap<string, number>,
): string | null {
  const objectives = topic.objective_ids
    .flatMap((id) => {
      const number = objectiveNumber.get(id);
      return number === undefined ? [] : [number];
    })
    .toSorted((a, b) => a - b);
  const needs = prerequisiteTitles(topic, everyItem);
  const parts: string[] = [];
  if (objectives.length > 0) {
    parts.push(
      `Supports ${objectives.length === 1 ? "objective" : "objectives"} ${objectives.join(", ")}`,
    );
  }
  if (needs.length > 0) parts.push(`Needs: ${needs.join(", ")}`);
  return parts.length > 0 ? parts.join(" · ") : null;
}

function ItemCard({ item, footer }: { item: RoadmapItem; footer: ReactNode }) {
  return (
    <li className="space-y-2 rounded-lg border bg-background p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <h4 className="font-medium">{item.title}</h4>
        <div className="flex flex-wrap gap-2">
          {item.day_number !== null ? (
            <Badge variant="secondary">Day {item.day_number}</Badge>
          ) : null}
          <Badge variant="outline">{formatMinutes(item.estimated_minutes)}</Badge>
          {item.kind === "revision" ? <Badge variant="info">Revision</Badge> : null}
          {item.kind === "enrichment" ? <Badge variant="outline">Optional</Badge> : null}
        </div>
      </div>
      <p className="text-sm text-muted-foreground">{item.description}</p>
      {item.practice_task ? (
        <p className="text-sm">
          <span className="font-medium">Practice: </span>
          {item.practice_task}
        </p>
      ) : null}
      {footer ? <p className="text-xs text-muted-foreground">{footer}</p> : null}
    </li>
  );
}
