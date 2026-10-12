import { describe, expect, it } from "vitest";

import type { GenerationJob, Roadmap, RoadmapItem, RoadmapSummary } from "@/lib/api/server";
import { noticeFor } from "@/lib/goals/notices";
import {
  describeStage,
  formatMinutes,
  itemKindLabel,
  pluralize,
  syllabusBasisNote,
} from "@/lib/roadmaps/labels";
import { parseVersion, roadmapPath } from "@/lib/roadmaps/paths";
import { allTopics, prerequisiteTitles, scheduleByDay } from "@/lib/roadmaps/schedule";
import { roadmapPanelState } from "@/lib/roadmaps/state";

const GOAL = "11111111-1111-4111-8111-111111111111";

function job(overrides: Partial<GenerationJob> = {}): GenerationJob {
  return {
    id: "22222222-2222-4222-8222-222222222222",
    goal_id: GOAL,
    job_type: "roadmap",
    item_id: null,
    status: "queued",
    stage: "queued",
    progress: 0,
    attempts: 0,
    max_attempts: 3,
    cancel_requested: false,
    error_code: null,
    error_message: null,
    roadmap_id: null,
    lesson_id: null,
    attempt_id: null,
    document_id: null,
    quiz_id: null,
    created_at: "2026-10-11T10:00:00Z",
    started_at: null,
    finished_at: null,
    ...overrides,
  };
}

function version(overrides: Partial<RoadmapSummary> = {}): RoadmapSummary {
  return {
    id: "33333333-3333-4333-8333-333333333333",
    goal_id: GOAL,
    version: 1,
    status: "current",
    title: "A plan",
    language: "en",
    topic_count: 3,
    total_minutes: 120,
    total_days: 3,
    daily_minutes: 60,
    target_date: null,
    revision_feedback: null,
    based_on_roadmap_id: null,
    is_synthetic: false,
    completed_topics: 0,
    created_at: "2026-10-11T09:00:00Z",
    ...overrides,
  };
}

function item(overrides: Partial<RoadmapItem>): RoadmapItem {
  return {
    id: "i1",
    kind: "topic",
    position: 1,
    key: "one",
    title: "One",
    description: "First",
    practice_task: "Do it",
    objective_ids: ["o1"],
    estimated_minutes: 30,
    day_number: 1,
    prerequisite_ids: [],
    study: { status: "not_started", has_lesson: false, sections_done: 0, sections_total: 0 },
    ...overrides,
  };
}

describe("paths", () => {
  it("links to the current roadmap or to one version", () => {
    expect(roadmapPath(GOAL)).toBe(`/goals/${GOAL}/roadmap`);
    expect(roadmapPath(GOAL, 3)).toBe(`/goals/${GOAL}/roadmap?version=3`);
  });

  it.each([
    ["2", 2],
    ["12", 12],
    ["999999", 999999],
  ])("reads ?version=%s", (raw, expected) => {
    expect(parseVersion(raw)).toBe(expected);
  });

  it.each([undefined, "", "0", "-1", "1.5", "abc", "1e3", "2 ", "0002", "1000000"])(
    "treats %j as 'the current one'",
    (raw) => {
      expect(parseVersion(raw)).toBeUndefined();
    },
  );
});

describe("labels", () => {
  it("describes each stage in plain words", () => {
    expect(describeStage({ status: "queued", stage: "queued" })).toMatch(/waiting/i);
    expect(describeStage({ status: "running", stage: "planning" })).toMatch(/planning/i);
    expect(describeStage({ status: "running", stage: "validated" })).toMatch(/checking/i);
    expect(describeStage({ status: "queued", stage: "waiting_retry" })).toMatch(/trying again/i);
    expect(describeStage({ status: "running", stage: "something-new" })).toBe("Working on it…");
  });

  it.each([
    [0, "0 min"],
    [45, "45 min"],
    [60, "1 h"],
    [75, "1 h 15 min"],
    [260, "4 h 20 min"],
    [-5, "0 min"],
  ])("formats %d minutes as %s", (minutes, text) => {
    expect(formatMinutes(minutes)).toBe(text);
  });

  it("pluralizes", () => {
    expect(pluralize(1, "day")).toBe("1 day");
    expect(pluralize(7, "day")).toBe("7 days");
    expect(pluralize(0, "study day")).toBe("0 study days");
  });

  it("never calls a plan official unless it was built from the learner's own material", () => {
    expect(syllabusBasisNote("general_knowledge")).toMatch(/not an official syllabus/);
    expect(syllabusBasisNote("learner_stated")).toMatch(/not an official syllabus/);
    expect(syllabusBasisNote("uploaded_document")).not.toMatch(/official/);
    expect(syllabusBasisNote("uploaded_document")).toMatch(/material you uploaded/);
  });

  it("names the kinds of item", () => {
    expect(itemKindLabel("topic")).toBe("Topic");
    expect(itemKindLabel("revision")).toBe("Revision");
    expect(itemKindLabel("enrichment")).toBe("Optional");
  });
});

describe("schedule", () => {
  const roadmap = {
    modules: [
      {
        id: "m1",
        position: 1,
        title: "M",
        summary: "S",
        topics: [
          item({ id: "a", position: 1, title: "A", day_number: 1, estimated_minutes: 40 }),
          item({ id: "b", position: 2, title: "B", day_number: 1, estimated_minutes: 20 }),
          item({ id: "c", position: 3, title: "C", day_number: 3, estimated_minutes: 50 }),
        ],
      },
    ],
    revision_sessions: [
      item({
        id: "r",
        kind: "revision",
        position: 4,
        title: "Revise",
        day_number: 3,
        estimated_minutes: 10,
      }),
    ],
  } satisfies Pick<Roadmap, "modules" | "revision_sessions">;

  it("groups scheduled items under their day, in order, with the day's minutes", () => {
    const days = scheduleByDay(roadmap);

    expect(days.map((d) => [d.day, d.minutes, d.items.map((i) => i.title)])).toEqual([
      [1, 60, ["A", "B"]],
      [3, 60, ["C", "Revise"]],
    ]);
  });

  it("leaves unscheduled enrichment out", () => {
    const withExtra = {
      ...roadmap,
      revision_sessions: [
        ...roadmap.revision_sessions,
        item({ id: "e", kind: "enrichment", day_number: null, title: "Extra" }),
      ],
    };

    expect(scheduleByDay(withExtra).flatMap((d) => d.items.map((i) => i.title))).not.toContain(
      "Extra",
    );
  });

  it("lists every topic across modules", () => {
    expect(allTopics(roadmap).map((t) => t.title)).toEqual(["A", "B", "C"]);
  });

  it("names prerequisites in plan order, ignoring ids it does not know", () => {
    const everything = [...allTopics(roadmap), ...roadmap.revision_sessions];

    expect(prerequisiteTitles({ prerequisite_ids: ["c", "a", "missing"] }, everything)).toEqual([
      "A",
      "C",
    ]);
    expect(prerequisiteTitles({ prerequisite_ids: [] }, everything)).toEqual([]);
  });
});

describe("roadmapPanelState", () => {
  it("invites the learner to start when there is nothing yet", () => {
    expect(roadmapPanelState([], [])).toEqual({ kind: "none" });
  });

  it("treats a cancelled job with nothing else as nothing yet", () => {
    expect(roadmapPanelState([job({ status: "cancelled" })], [])).toEqual({ kind: "none" });
  });

  it.each(["queued", "running"] as const)("shows progress for a %s job", (status) => {
    const active = job({ status });

    expect(roadmapPanelState([active], [])).toEqual({ kind: "generating", job: active });
  });

  it("progress wins over an existing plan: the learner is waiting for the new one", () => {
    const active = job({ status: "running" });
    const state = roadmapPanelState([active, job({ status: "completed" })], [version()]);

    expect(state.kind).toBe("generating");
  });

  it("shows the current roadmap once the work is done", () => {
    const current = version({ version: 2 });
    const older = version({ id: "x", version: 1, status: "superseded" });

    expect(roadmapPanelState([job({ status: "completed" })], [current, older])).toEqual({
      kind: "ready",
      current,
      versions: 2,
    });
  });

  it("shows a failed job when it is newer than every roadmap, keeping the older plan reachable", () => {
    const failed = job({ status: "failed", created_at: "2026-10-11T11:00:00Z" });
    const current = version({ created_at: "2026-10-11T09:00:00Z" });

    expect(roadmapPanelState([failed], [current])).toEqual({
      kind: "failed",
      job: failed,
      current,
    });
  });

  it("shows a failure with no plan at all", () => {
    const failed = job({ status: "failed" });

    expect(roadmapPanelState([failed], [])).toEqual({ kind: "failed", job: failed, current: null });
  });

  it("stops showing a failure once a newer roadmap exists", () => {
    const failed = job({ status: "failed", created_at: "2026-10-11T08:00:00Z" });
    const current = version({ created_at: "2026-10-11T09:00:00Z" });

    expect(roadmapPanelState([failed], [current]).kind).toBe("ready");
  });

  it("compares moments, not text, so different time zone spellings still order correctly", () => {
    const failed = job({ status: "failed", created_at: "2026-10-11T11:00:00+00:00" });
    const current = version({ created_at: "2026-10-11T12:30:00+02:00" }); // 10:30 UTC

    expect(roadmapPanelState([failed], [current]).kind).toBe("failed");
  });
});

describe("notices used by the roadmap actions", () => {
  it.each([
    "already-generating",
    "generation-cancelled",
    "version-switched",
    "needs-detail",
    "ai-unavailable",
    "generation-limit",
    "goal-archived",
  ])("%s has a message", (code) => {
    expect(noticeFor(code)?.title).toBeTruthy();
  });
});
