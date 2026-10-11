import Link from "next/link";

import { MasteryBadge } from "@/components/quiz/mastery";
import { Badge } from "@/components/ui/badge";
import type { TopicProgress } from "@/lib/api/server";
import { studyPath } from "@/lib/lessons/paths";
import { studySummary } from "@/lib/lessons/labels";
import { formatPercent } from "@/lib/quizzes/labels";
import { resultsPath } from "@/lib/quizzes/paths";

/**
 * Every topic of a roadmap with where the learner stands on it: its mastery band and score once a
 * quiz has been marked, otherwise how far the studying has got and whether a quiz is waiting. The
 * band is written out, never only coloured, and a weak topic says so in words.
 */
export function TopicProgressList({
  goalId,
  topics,
}: {
  goalId: string;
  topics: readonly TopicProgress[];
}) {
  return (
    <ol className="divide-y rounded-xl border bg-card" aria-label="Progress by topic">
      {topics.map((topic) => {
        const mastery = topic.mastery;
        return (
          <li key={topic.item_id} className="flex flex-wrap items-center gap-x-4 gap-y-2 p-4">
            <div className="min-w-0 flex-1 space-y-1">
              <Link
                href={studyPath(goalId, topic.item_id)}
                className="font-medium underline-offset-4 hover:underline"
              >
                {topic.title}
              </Link>
              <p className="text-xs text-muted-foreground">
                {topic.module_title ? `${topic.module_title} · ` : ""}
                {studySummary(topic.study)}
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {mastery ? (
                <>
                  <MasteryBadge band={mastery.band} />
                  <span className="text-sm tabular-nums">
                    <span className="sr-only">Score </span>
                    {formatPercent(mastery.score)}
                  </span>
                  {mastery.low_confidence ? <Badge variant="outline">Early estimate</Badge> : null}
                </>
              ) : (
                <Badge variant="outline">Not assessed yet</Badge>
              )}
              {topic.pending_quiz_id ? <Badge variant="info">Quiz waiting</Badge> : null}
              {topic.last_attempt ? (
                <Link
                  href={resultsPath(goalId, topic.item_id, topic.last_attempt.id)}
                  className="text-sm text-primary underline-offset-4 hover:underline"
                >
                  Results
                  <span className="sr-only"> for {topic.title}</span>
                </Link>
              ) : null}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
