import { Badge } from "@/components/ui/badge";
import { ProgressBar } from "@/components/progress/progress-bar";
import type { MasteryBand, TopicMastery } from "@/lib/api/server";
import { bandExplanation, bandLabel, bandVariant, formatPercent } from "@/lib/quizzes/labels";

/** The band a topic is in ("Needs practice"), as a badge. */
export function MasteryBadge({ band }: { band: MasteryBand }) {
  return <Badge variant={bandVariant(band)}>{bandLabel(band)}</Badge>;
}

type MasteryMeterProps = {
  mastery: TopicMastery;
  /** Label of the bar; defaults to "Mastery". */
  label?: string;
  /** Also explain how the score was reached and what the band means. */
  detailed?: boolean;
};

/**
 * A topic's mastery: the score, the band and, when asked, where it comes from. The wording is plain
 * about the evidence: a score built from very few answers is called an early estimate.
 */
export function MasteryMeter({ mastery, label = "Mastery", detailed = false }: MasteryMeterProps) {
  const attempts = mastery.attempts_count === 1 ? "1 quiz" : `${mastery.attempts_count} quizzes`;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <MasteryBadge band={mastery.band} />
        {mastery.low_confidence ? <Badge variant="outline">Early estimate</Badge> : null}
      </div>
      <ProgressBar
        label={label}
        value={mastery.score}
        description={
          detailed
            ? `Based on ${attempts} and ${mastery.answers_count} answers. ${bandExplanation(mastery.band, mastery)}`
            : undefined
        }
      />
      <p className="sr-only">
        {label}: {formatPercent(mastery.score)}, {bandLabel(mastery.band)}.
      </p>
    </div>
  );
}
