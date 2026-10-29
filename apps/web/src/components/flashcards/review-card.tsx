import { Button } from "@/components/ui/button";
import { reviewFlashcardAction } from "@/lib/flashcards/actions";
import { RATING_OPTIONS } from "@/lib/flashcards/labels";

type ReviewCardProps = {
  goalId: string;
  cardId: string;
  front: string;
  back: string;
  /** Made by the page for this showing of the card, so a double click counts once. */
  reviewKey: string;
};

/**
 * One card to review: the front, a native "Show answer" disclosure, and, once the answer is
 * open, four rating buttons. Revealing needs no script and no server round trip; the rating is a
 * plain form post to a Server Action, so it works without JavaScript too. The browser sends only
 * the rating and the key: the server decides when the card comes back.
 */
export function ReviewCard({ goalId, cardId, front, back, reviewKey }: ReviewCardProps) {
  return (
    <article className="space-y-6 rounded-2xl border bg-card p-6 shadow-xs sm:p-8">
      <section aria-labelledby="front-heading" className="space-y-2">
        <h2
          id="front-heading"
          className="text-xs font-medium uppercase tracking-wide text-muted-foreground"
        >
          Question
        </h2>
        <p className="whitespace-pre-wrap text-lg leading-8">{front}</p>
      </section>

      <details className="group space-y-6">
        <summary className="inline-flex cursor-pointer items-center rounded-lg border bg-background px-4 py-2 text-sm font-medium outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background group-open:hidden">
          Show answer
        </summary>
        <section aria-labelledby="back-heading" className="space-y-2 border-t pt-6">
          <h2
            id="back-heading"
            className="text-xs font-medium uppercase tracking-wide text-muted-foreground"
          >
            Answer
          </h2>
          <p className="whitespace-pre-wrap text-lg leading-8">{back}</p>
        </section>
        <form action={reviewFlashcardAction.bind(null, goalId, cardId)} className="space-y-3">
          <input type="hidden" name="key" value={reviewKey} />
          <fieldset className="space-y-3">
            <legend className="text-sm font-medium">How well did you remember it?</legend>
            <div className="grid gap-2 sm:grid-cols-4">
              {RATING_OPTIONS.map((option) => (
                <Button
                  key={option.value}
                  type="submit"
                  name="rating"
                  value={option.value}
                  variant={option.value === "good" ? "default" : "outline"}
                  className="h-auto flex-col gap-0.5 py-3"
                >
                  <span>{option.label}</span>
                  <span className="text-xs font-normal opacity-80">{option.hint}</span>
                </Button>
              ))}
            </div>
          </fieldset>
        </form>
      </details>
    </article>
  );
}
