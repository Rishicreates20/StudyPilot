import { describe, expect, it } from "vitest";

import type { RoadmapItem } from "@/lib/api/server";
import { parseInline } from "@/lib/lessons/inline";
import {
  adjustLabel,
  describeLessonStage,
  isLessonAdjust,
  studyActionLabel,
  studyStatusLabel,
  studySummary,
} from "@/lib/lessons/labels";
import { studyPath } from "@/lib/lessons/paths";
import {
  continueTarget,
  resumeSectionId,
  studyPanelState,
  summarizeProgress,
} from "@/lib/lessons/state";
import { GOAL, ITEM, LESSON, lesson, lessonJob, progress, study } from "@/test-support/lessons";

describe("studyPath", () => {
  it("builds the page of a topic, optionally at an earlier version", () => {
    expect(studyPath(GOAL, ITEM)).toBe(`/goals/${GOAL}/learn/${ITEM}`);
    expect(studyPath(GOAL, ITEM, LESSON)).toBe(`/goals/${GOAL}/learn/${ITEM}?lesson=${LESSON}`);
  });
});

describe("parseInline", () => {
  it("splits plain text, `code` and **bold**", () => {
    expect(parseInline("Use `let` to **bind** a value.")).toEqual([
      { kind: "text", text: "Use " },
      { kind: "code", text: "let" },
      { kind: "text", text: " to " },
      { kind: "strong", text: "bind" },
      { kind: "text", text: " a value." },
    ]);
  });

  it.each([
    ["no markup at all", [{ kind: "text", text: "no markup at all" }]],
    ["an `unclosed backtick", [{ kind: "text", text: "an `unclosed backtick" }]],
    ["a lone * star and ** pair", [{ kind: "text", text: "a lone * star and ** pair" }]],
    ["empty `` code", [{ kind: "text", text: "empty `` code" }]],
    ["", []],
  ])("leaves %j alone", (input, expected) => {
    expect(parseInline(input)).toEqual(expected);
  });

  it("never turns text into markup: tags and links stay text", () => {
    const hostile =
      '<img src=x onerror="alert(1)"> [click](javascript:alert(1)) <script>x</script>';

    const parts = parseInline(hostile);

    expect(parts).toEqual([{ kind: "text", text: hostile }]);
  });

  it("does not look for bold inside code", () => {
    expect(parseInline("`**not bold**`")).toEqual([{ kind: "code", text: "**not bold**" }]);
  });
});

describe("labels", () => {
  it("describes each stage of a lesson job in words", () => {
    expect(describeLessonStage({ status: "queued", stage: "queued" })).toMatch(/waiting/i);
    expect(describeLessonStage({ status: "running", stage: "writing" })).toBe(
      "Writing your lesson…",
    );
    expect(describeLessonStage({ status: "queued", stage: "waiting_retry" })).toMatch(/busy/i);
    expect(describeLessonStage({ status: "running", stage: "something-new" })).toBe(
      "Working on it…",
    );
  });

  it("knows the three ways a lesson can be asked to differ", () => {
    expect(isLessonAdjust("simpler")).toBe(true);
    expect(isLessonAdjust("deeper")).toBe(true);
    expect(isLessonAdjust("angrier")).toBe(false);
    expect(isLessonAdjust("")).toBe(false);
    expect(adjustLabel("more_examples")).toBe("More examples");
    expect(adjustLabel(null)).toBeNull();
  });

  it("summarises and labels a topic's study state", () => {
    expect(studySummary(study())).toBe("Not started");
    expect(studySummary(study({ has_lesson: true }))).toBe("Lesson ready");
    expect(
      studySummary(
        study({ status: "in_progress", has_lesson: true, sections_done: 2, sections_total: 5 }),
      ),
    ).toBe("2 of 5 sections");
    expect(studySummary(study({ status: "completed", has_lesson: true }))).toBe("Done");
    expect(studyStatusLabel("in_progress")).toBe("In progress");
    expect(studyActionLabel(study())).toBe("Open lesson");
    expect(studyActionLabel(study({ has_lesson: true }))).toBe("Start studying");
    expect(studyActionLabel(study({ status: "in_progress", has_lesson: true }))).toBe("Continue");
    expect(studyActionLabel(study({ status: "completed", has_lesson: true }))).toBe("Review");
  });
});

describe("studyPanelState", () => {
  it("offers to write a lesson when there is neither a lesson nor a job", () => {
    expect(studyPanelState({ lesson: null, job: null })).toEqual({ kind: "empty" });
  });

  it.each(["queued", "running"] as const)(
    "shows a %s job when there is no lesson yet",
    (status) => {
      const job = lessonJob({ status });

      expect(studyPanelState({ lesson: null, job })).toEqual({ kind: "generating", job });
    },
  );

  it("shows a failure, with its job, when the last attempt failed and there is no lesson", () => {
    const job = lessonJob({ status: "failed", error_code: "LESSON_INVALID" });

    expect(studyPanelState({ lesson: null, job })).toEqual({ kind: "failed", job });
  });

  it("ignores a cancelled or completed job when there is no lesson", () => {
    expect(studyPanelState({ lesson: null, job: lessonJob({ status: "cancelled" }) })).toEqual({
      kind: "empty",
    });
    expect(studyPanelState({ lesson: null, job: lessonJob({ status: "completed" }) })).toEqual({
      kind: "empty",
    });
  });

  it("always shows an existing lesson, and reports a new version being written beside it", () => {
    const shown = lesson();
    const job = lessonJob({ status: "running" });

    expect(studyPanelState({ lesson: shown, job })).toEqual({
      kind: "ready",
      lesson: shown,
      writing: job,
      failedNewer: null,
    });
  });

  it("reports a failed new version only if it is newer than the lesson shown", () => {
    const shown = lesson({ created_at: "2026-10-11T10:00:00Z" });
    const newer = lessonJob({ status: "failed", created_at: "2026-10-11T11:00:00Z" });
    const older = lessonJob({ status: "failed", created_at: "2026-10-11T09:00:00Z" });

    expect(studyPanelState({ lesson: shown, job: newer })).toMatchObject({ failedNewer: newer });
    expect(studyPanelState({ lesson: shown, job: older })).toMatchObject({ failedNewer: null });
  });
});

describe("summarizeProgress", () => {
  const ids = ["s1", "s2", "s3", "s4"];

  it("counts only sections that belong to the lesson", () => {
    const summary = summarizeProgress(
      ids,
      progress({ completed_section_ids: ["s1", "s2", "s99"] }),
    );

    expect(summary).toEqual({ done: 2, total: 4, percent: 50, completed: false });
  });

  it("starts at zero without saved progress, and handles an empty lesson", () => {
    expect(summarizeProgress(ids, null)).toEqual({
      done: 0,
      total: 4,
      percent: 0,
      completed: false,
    });
    expect(summarizeProgress([], null)).toEqual({
      done: 0,
      total: 0,
      percent: 0,
      completed: false,
    });
  });

  it("reports a finished lesson", () => {
    const summary = summarizeProgress(
      ids,
      progress({ status: "completed", completed_section_ids: ids }),
    );

    expect(summary).toMatchObject({ percent: 100, completed: true });
  });
});

describe("resumeSectionId", () => {
  const ids = ["s1", "s2", "s3"];

  it("returns the saved place when it is a later section of this lesson", () => {
    expect(resumeSectionId(ids, progress({ current_section_id: "s2" }))).toBe("s2");
  });

  it.each([
    ["nothing saved", null],
    ["still on the first section", progress({ current_section_id: "s1" })],
    ["no place recorded", progress({ current_section_id: null })],
    ["a section that no longer exists", progress({ current_section_id: "s9" })],
    ["a finished lesson", progress({ status: "completed", current_section_id: "s3" })],
  ])("starts at the top for %s", (_label, saved) => {
    expect(resumeSectionId(ids, saved)).toBeNull();
  });
});

describe("continueTarget", () => {
  function topic(id: string, status: "not_started" | "in_progress" | "completed"): RoadmapItem {
    return {
      id,
      kind: "topic",
      position: 1,
      key: id,
      title: id,
      description: "d",
      practice_task: "p",
      objective_ids: [],
      estimated_minutes: 30,
      day_number: 1,
      prerequisite_ids: [],
      study: study({ status, has_lesson: status !== "not_started" }),
    };
  }

  it("prefers the topic the learner is part-way through", () => {
    const topics = [topic("a", "completed"), topic("b", "not_started"), topic("c", "in_progress")];

    expect(continueTarget(topics)?.id).toBe("c");
  });

  it("otherwise takes the first topic that is not finished", () => {
    const topics = [topic("a", "completed"), topic("b", "not_started"), topic("c", "not_started")];

    expect(continueTarget(topics)?.id).toBe("b");
  });

  it("is null when everything is finished or there is nothing", () => {
    expect(continueTarget([topic("a", "completed")])).toBeNull();
    expect(continueTarget([])).toBeNull();
  });
});
