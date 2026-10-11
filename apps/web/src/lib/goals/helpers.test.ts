import { afterEach, describe, expect, it, vi } from "vitest";

import { describeDaysAway, daysBetween, formatDate, formatMoment, todayIn } from "@/lib/format";
import { editGoalPath, goalPath, isGoalId, isGoalStatus } from "@/lib/goals/ids";
import { noticeFor } from "@/lib/goals/notices";
import { failureMessage } from "@/lib/api/failure";
import { ApiError } from "@/lib/api/server";

describe("isGoalId", () => {
  it.each([
    "11111111-1111-4111-8111-111111111111",
    "AAAAAAAA-BBBB-4CCC-8DDD-EEEEEEEEEEEE", // upper case is a valid UUID
  ])("accepts %s", (id) => {
    expect(isGoalId(id)).toBe(true);
  });

  it.each([
    "",
    "summary",
    "not-a-uuid",
    "../me",
    "11111111-1111-4111-8111-11111111111", // one short
    "11111111-1111-4111-8111-1111111111111", // one long
    "11111111-1111-4111-8111-111111111111/status",
    "11111111-1111-4111-8111-111111111111?x=1",
    " 11111111-1111-4111-8111-111111111111",
    null,
    undefined,
    42,
    { toString: () => "11111111-1111-4111-8111-111111111111" },
  ])("refuses %j, so it can never reach an API path", (value) => {
    expect(isGoalId(value)).toBe(false);
  });

  it("builds paths only from the checked ID", () => {
    expect(goalPath("11111111-1111-4111-8111-111111111111")).toBe(
      "/goals/11111111-1111-4111-8111-111111111111",
    );
    expect(editGoalPath("11111111-1111-4111-8111-111111111111")).toBe(
      "/goals/11111111-1111-4111-8111-111111111111/edit",
    );
  });
});

describe("isGoalStatus", () => {
  it.each(["active", "paused", "completed", "archived"])("accepts %s", (status) => {
    expect(isGoalStatus(status)).toBe(true);
  });

  it.each(["", "deleted", "ACTIVE", "__proto__", "constructor", null, undefined, 1])(
    "refuses %j",
    (status) => {
      expect(isGoalStatus(status)).toBe(false);
    },
  );
});

describe("noticeFor", () => {
  it.each([
    "created",
    "updated",
    "paused",
    "active",
    "completed",
    "archived",
    "deleted",
    "onboarded",
    "skipped",
    "status-conflict",
    "limit-reached",
    "not-archived",
    "unavailable",
  ])("has wording for %s", (code) => {
    const notice = noticeFor(code);

    expect(notice).not.toBeNull();
    expect(notice?.title).toBeTruthy();
  });

  it.each([undefined, "", "unknown", "constructor", "toString", "__proto__", "hasOwnProperty"])(
    "has nothing for %j",
    (code) => {
      expect(noticeFor(code)).toBeNull();
    },
  );

  it("marks refusals as warnings, not successes", () => {
    for (const code of ["status-conflict", "limit-reached", "not-archived", "unavailable"]) {
      expect(noticeFor(code)?.variant).toBe("warning");
    }
  });
});

describe("dates", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("formats a date-only value the same everywhere", () => {
    expect(formatDate("2027-01-31")).toBe("31 Jan 2027");
  });

  it("shows a moment in the learner's own timezone", () => {
    // 20:00 UTC on the 9th is already the 10th in Kolkata (UTC+5:30).
    expect(formatMoment("2026-10-09T20:00:00Z", "Asia/Kolkata")).toBe("10 Oct 2026");
    expect(formatMoment("2026-10-09T20:00:00Z", "UTC")).toBe("9 Oct 2026");
  });

  it("falls back to UTC for a timezone it doesn't know instead of failing the page", () => {
    expect(formatMoment("2026-10-09T20:00:00Z", "Mars/Olympus_Mons")).toBe("9 Oct 2026");
  });

  it("works out today's date where the learner is", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-09T20:00:00Z"));

    expect(todayIn("Asia/Kolkata")).toBe("2026-10-10");
    expect(todayIn("America/Los_Angeles")).toBe("2026-10-09");
    expect(todayIn("Not/AZone")).toBe("2026-10-09"); // UTC fallback
  });

  it.each([
    ["2026-10-10", "2026-10-10", 0],
    ["2026-10-10", "2026-10-11", 1],
    ["2026-10-10", "2026-10-09", -1],
    ["2026-10-10", "2027-01-31", 113],
    ["2026-12-31", "2027-01-01", 1], // across a year
    ["2027-02-28", "2027-03-01", 1], // across a month, not a leap year
  ])("counts the days from %s to %s: %i", (today, target, days) => {
    expect(daysBetween(today, target)).toBe(days);
  });

  it.each([
    [0, "today"],
    [1, "tomorrow"],
    [-1, "yesterday"],
    [12, "in 12 days"],
    [-9, "9 days ago"],
  ])("describes %i days as '%s'", (days, text) => {
    expect(describeDaysAway(days)).toBe(text);
  });
});

describe("failureMessage", () => {
  it.each([
    "GOAL_LIMIT_REACHED",
    "GOAL_ARCHIVED",
    "GOAL_NOT_ARCHIVED",
    "INVALID_STATUS_TRANSITION",
  ])("passes through the API's own wording for %s", (code) => {
    expect(failureMessage(new ApiError(409, code, "Written for the learner."), "goal")).toBe(
      "Written for the learner.",
    );
  });

  it("says plainly that nothing was saved when the service is down", () => {
    for (const status of [0, 503]) {
      expect(failureMessage(new ApiError(status, "X", "down"), "preferences")).toContain(
        "nothing was saved",
      );
    }
  });

  it("never shows an unexpected server message, only a reference", () => {
    const message = failureMessage(
      new ApiError(500, "INTERNAL_ERROR", "psycopg.OperationalError: host 10.0.0.5", {
        requestId: "req-1",
      }),
      "goal",
    );

    expect(message).toContain("req-1");
    expect(message).not.toContain("10.0.0.5");
  });
});
