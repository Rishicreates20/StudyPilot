import { describe, expect, it } from "vitest";

import { zodFieldErrors } from "@/lib/forms";
import { goalFormSchema, mapApiFieldErrors } from "@/lib/goals/schema";

const valid = {
  title: "Learn Kubernetes",
  description: "",
  goalType: "interview",
  currentLevel: "beginner",
  targetDate: "",
  dailyMinutes: "90",
  languages: ["en", "hi"],
};

describe("goalFormSchema", () => {
  it("accepts a valid goal and converts the minutes to a number", () => {
    const result = goalFormSchema.safeParse(valid);

    expect(result.success && result.data.dailyMinutes).toBe(90);
  });

  it("trims the title", () => {
    const result = goalFormSchema.safeParse({ ...valid, title: "  Docker  " });

    expect(result.success && result.data.title).toBe("Docker");
  });

  it.each([
    [{ title: "" }, "title"],
    [{ title: "   " }, "title"],
    [{ title: "t".repeat(201) }, "title"],
    [{ description: "d".repeat(2001) }, "description"],
    [{ goalType: "hobby" }, "goalType"],
    [{ currentLevel: "expert" }, "currentLevel"],
    [{ dailyMinutes: "9" }, "dailyMinutes"],
    [{ dailyMinutes: "481" }, "dailyMinutes"],
    [{ dailyMinutes: "lots" }, "dailyMinutes"],
    [{ dailyMinutes: "45.5" }, "dailyMinutes"],
    [{ targetDate: "08/11/2026" }, "targetDate"],
    [{ languages: [] }, "languages"],
    [{ languages: ["fr"] }, "languages"],
  ])("rejects %j with a message on %s", (override, field) => {
    const result = goalFormSchema.safeParse({ ...valid, ...override });

    expect(result.success).toBe(false);
    if (!result.success) expect(zodFieldErrors(result.error)[field]).toBeDefined();
  });

  it("accepts an optional target date in ISO form", () => {
    expect(goalFormSchema.safeParse({ ...valid, targetDate: "2026-12-31" }).success).toBe(true);
  });
});

describe("mapApiFieldErrors", () => {
  it("renames API (snake_case) fields to form fields", () => {
    expect(
      mapApiFieldErrors({
        title: "bad title",
        goal_type: "bad type",
        current_level: "bad level",
        target_date: "past",
        daily_minutes: "too many",
        preferred_languages: "unsupported",
        description: "too long",
      }),
    ).toEqual({
      title: "bad title",
      goalType: "bad type",
      currentLevel: "bad level",
      targetDate: "past",
      dailyMinutes: "too many",
      languages: "unsupported",
      description: "too long",
    });
  });

  it("ignores fields the form does not have", () => {
    expect(mapApiFieldErrors({ user_id: "not allowed", status: "not allowed" })).toEqual({});
  });
});
