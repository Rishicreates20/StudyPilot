import { describe, expect, it } from "vitest";

import { cardStage, deckSentence, RATING_OPTIONS, whenDue } from "@/lib/flashcards/labels";
import { flashcardsPath, reviewPath } from "@/lib/flashcards/paths";
import {
  cardFormSchema,
  isRating,
  isReviewKey,
  MAX_BACK_CHARS,
  MAX_FRONT_CHARS,
  RATINGS,
} from "@/lib/flashcards/schema";

const NOW = new Date("2026-10-23T09:00:00Z");
const at = (offsetMs: number) => new Date(NOW.getTime() + offsetMs).toISOString();
const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

describe("whenDue", () => {
  it("says a card is due now when the server says so, whatever the browser's clock thinks", () => {
    // The due time is in the future by this clock, but the server decided it is due.
    expect(whenDue({ is_due: true, due_at: at(DAY) }, NOW)).toBe("Due now");
  });

  it("does not call a card due when the server says it is not, even if the browser clock is ahead", () => {
    const farFuture = new Date(NOW.getTime() + 10 * DAY);
    expect(whenDue({ is_due: false, due_at: at(DAY) }, farFuture)).toMatch(/^Due in 1 minute$/);
  });

  it.each([
    [10 * MINUTE, "Due in 10 minutes"],
    [MINUTE, "Due in 1 minute"],
    [30_000, "Due in 1 minute"],
    [2 * HOUR, "Due in 2 hours"],
    [HOUR, "Due in 1 hour"],
    [DAY, "Due tomorrow"],
    [6 * DAY, "Due in 6 days"],
    [40 * DAY, "Due in 40 days"],
  ])("words a wait of %i ms as %s", (wait, expected) => {
    expect(whenDue({ is_due: false, due_at: at(wait) }, NOW)).toBe(expected);
  });
});

describe("cardStage", () => {
  it.each([
    [{ repetitions: 0, lapses: 0, last_reviewed_at: null }, "New"],
    [{ repetitions: 0, lapses: 2, last_reviewed_at: "2026-10-22T09:00:00Z" }, "Relearning"],
    [{ repetitions: 1, lapses: 0, last_reviewed_at: "2026-10-22T09:00:00Z" }, "Learning"],
    [{ repetitions: 2, lapses: 0, last_reviewed_at: "2026-10-22T09:00:00Z" }, "Learning"],
    [{ repetitions: 3, lapses: 0, last_reviewed_at: "2026-10-22T09:00:00Z" }, "Review"],
  ])("labels %j as %s", (card, expected) => {
    expect(cardStage(card)).toBe(expected);
  });
});

describe("deckSentence", () => {
  it.each([
    [{ total: 0, due_now: 0 }, "No cards yet."],
    [{ total: 1, due_now: 0 }, "1 card. Nothing is due right now."],
    [{ total: 5, due_now: 0 }, "5 cards. Nothing is due right now."],
    [{ total: 5, due_now: 3 }, "5 cards. 3 due now."],
  ])("describes %j", (summary, expected) => {
    expect(deckSentence(summary)).toBe(expected);
  });
});

describe("the form schema", () => {
  it("trims both sides and accepts a normal card", () => {
    expect(cardFormSchema.parse({ front: "  What?  ", back: "  That.  " })).toEqual({
      front: "What?",
      back: "That.",
    });
  });

  it.each([
    [{ front: "", back: "B" }, "front"],
    [{ front: "   ", back: "B" }, "front"],
    [{ front: "F", back: "" }, "back"],
    [{ front: "x".repeat(MAX_FRONT_CHARS + 1), back: "B" }, "front"],
    [{ front: "F", back: "x".repeat(MAX_BACK_CHARS + 1) }, "back"],
  ])("rejects %j on the %s field", (input, field) => {
    const result = cardFormSchema.safeParse(input);
    expect(result.success).toBe(false);
    expect(result.error?.issues[0]?.path[0]).toBe(field);
  });

  it("mirrors the API's limits", () => {
    expect(MAX_FRONT_CHARS).toBe(1000);
    expect(MAX_BACK_CHARS).toBe(2000);
  });
});

describe("ratings and keys", () => {
  it("offers exactly the four ratings the API accepts, hardest first", () => {
    expect(RATINGS).toEqual(["again", "hard", "good", "easy"]);
    expect(RATING_OPTIONS.map((option) => option.value)).toEqual([...RATINGS]);
  });

  it.each(["again", "hard", "good", "easy"])("accepts the rating %s", (value) => {
    expect(isRating(value)).toBe(true);
  });

  it.each(["perfect", "", "GOOD", 5, null, undefined, "good "])(
    "refuses %j as a rating",
    (value) => {
      expect(isRating(value)).toBe(false);
    },
  );

  it.each(["3f2c1a7e-4d5b-4c6e-8f90-1234567890ab", "abcdefgh", "a".repeat(128)])(
    "accepts %s as a review key",
    (value) => {
      expect(isReviewKey(value)).toBe(true);
    },
  );

  it.each(["short", "has spaces in it", "semi;colon-1234", "a".repeat(129), "", null, 12345678])(
    "refuses %j as a review key",
    (value) => {
      expect(isReviewKey(value)).toBe(false);
    },
  );
});

describe("paths", () => {
  it("nests the deck and the review under the goal", () => {
    expect(flashcardsPath("abc")).toBe("/goals/abc/flashcards");
    expect(reviewPath("abc")).toBe("/goals/abc/flashcards/review");
  });
});
