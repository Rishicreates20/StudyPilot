import { describe, expect, it } from "vitest";

import type { Goal } from "@/lib/api/server";
import { zodFieldErrors } from "@/lib/forms";
import {
  goalFormSchema,
  goalToFormValues,
  mapApiFieldErrors,
  newGoalDefaults,
  quickGoalSchema,
  readGoalFormValues,
  toCreateBody,
  toUpdateBody,
} from "@/lib/goals/schema";

const valid = {
  title: "Learn Kubernetes",
  description: "",
  goalType: "interview",
  currentLevel: "beginner",
  targetDate: "",
  dailyMinutes: "90",
  languages: ["en", "hi"],
  learningPreferences: ["examples", "quizzes"],
};

function formData(entries: [string, string][]): FormData {
  const data = new FormData();
  for (const [name, value] of entries) data.append(name, value);
  return data;
}

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
    [{ learningPreferences: ["flashcards"] }, "learningPreferences"],
  ])("rejects %j with a message on %s", (override, field) => {
    const result = goalFormSchema.safeParse({ ...valid, ...override });

    expect(result.success).toBe(false);
    if (!result.success) expect(zodFieldErrors(result.error)[field]).toBeDefined();
  });

  it("accepts an optional target date in ISO form", () => {
    expect(goalFormSchema.safeParse({ ...valid, targetDate: "2026-12-31" }).success).toBe(true);
  });

  it("lets a learner choose no kinds of practice at all", () => {
    expect(goalFormSchema.safeParse({ ...valid, learningPreferences: [] }).success).toBe(true);
  });
});

describe("quickGoalSchema (the first goal in onboarding)", () => {
  const essentials = {
    title: "Learn Kubernetes",
    description: "",
    goalType: "interview",
    currentLevel: "unknown",
    targetDate: "",
  };

  it("needs only the essentials: no study time, languages or practice", () => {
    expect(quickGoalSchema.safeParse(essentials).success).toBe(true);
  });

  it("does not require a target date", () => {
    expect(quickGoalSchema.safeParse({ ...essentials, targetDate: "" }).success).toBe(true);
  });

  it("still insists on a title", () => {
    const result = quickGoalSchema.safeParse({ ...essentials, title: " " });

    expect(result.success).toBe(false);
  });
});

describe("request bodies", () => {
  const parsed = goalFormSchema.parse({ ...valid, targetDate: "2027-03-01", description: "Notes" });

  it("sends the choices to the API in its own field names, and never an owner", () => {
    const body = toCreateBody(parsed);

    expect(body).toEqual({
      title: "Learn Kubernetes",
      description: "Notes",
      goal_type: "interview",
      current_level: "beginner",
      target_date: "2027-03-01",
      daily_minutes: 90,
      preferred_languages: ["en", "hi"],
      learning_preferences: ["examples", "quizzes"],
    });
    expect(Object.keys(body)).not.toContain("user_id");
    expect(Object.keys(body)).not.toContain("status");
  });

  it("sends blank optional fields as null so an edit can clear them", () => {
    const cleared = goalFormSchema.parse({ ...valid, targetDate: "", description: "  " });

    expect(toUpdateBody(cleared)).toMatchObject({ description: null, target_date: null });
  });
});

describe("form values", () => {
  const goal: Goal = {
    id: "11111111-1111-4111-8111-111111111111",
    title: "Learn Kubernetes",
    description: null,
    goal_type: "certification",
    current_level: "intermediate",
    target_date: "2027-03-01",
    daily_minutes: 45,
    preferred_languages: ["hi"],
    learning_preferences: ["revision"],
    status: "paused",
    completed_at: null,
    archived_at: null,
    created_at: "2026-10-09T00:00:00Z",
    updated_at: "2026-10-09T00:00:00Z",
  };

  it("turns a stored goal into the edit form's starting values", () => {
    expect(goalToFormValues(goal)).toEqual({
      title: "Learn Kubernetes",
      description: "",
      goalType: "certification",
      currentLevel: "intermediate",
      targetDate: "2027-03-01",
      dailyMinutes: "45",
      languages: ["hi"],
      learningPreferences: ["revision"],
    });
  });

  it("starts a new goal from the learner's saved preferences", () => {
    const defaults = newGoalDefaults({
      default_daily_minutes: 120,
      preferred_languages: ["or", "en"],
      learning_preferences: ["quizzes"],
    });

    expect(defaults).toMatchObject({
      title: "",
      dailyMinutes: "120",
      languages: ["or", "en"],
      learningPreferences: ["quizzes"],
      currentLevel: "unknown", // a level is never guessed
    });
  });

  it("falls back to sensible defaults when there are no saved preferences", () => {
    expect(newGoalDefaults()).toMatchObject({
      dailyMinutes: "60",
      languages: ["en"],
      learningPreferences: ["examples", "quizzes", "revision"],
    });
  });

  it("reads every field from a submission, keeping repeated checkboxes", () => {
    const values = readGoalFormValues(
      formData([
        ["title", "T"],
        ["goalType", "exam"],
        ["languages", "en"],
        ["languages", "hi"],
        ["learningPreferences", "quizzes"],
        ["user_id", "22222222-2222-4222-8222-222222222222"],
      ]),
    );

    expect(values.languages).toEqual(["en", "hi"]);
    expect(values.learningPreferences).toEqual(["quizzes"]);
    expect(Object.keys(values)).not.toContain("user_id"); // unknown fields are not carried along
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
        learning_preferences: "unknown kind",
        description: "too long",
      }),
    ).toEqual({
      title: "bad title",
      goalType: "bad type",
      currentLevel: "bad level",
      targetDate: "past",
      dailyMinutes: "too many",
      languages: "unsupported",
      learningPreferences: "unknown kind",
      description: "too long",
    });
  });

  it("ignores fields the form does not have", () => {
    expect(mapApiFieldErrors({ user_id: "not allowed", status: "not allowed" })).toEqual({});
  });
});
