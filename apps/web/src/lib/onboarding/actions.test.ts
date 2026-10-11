// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest";

const session = vi.hoisted(() => ({ getSessionUser: vi.fn(), getAccessToken: vi.fn() }));
const api = vi.hoisted(() => ({
  updateMe: vi.fn(),
  createGoal: vi.fn(),
  completeOnboarding: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  redirect: (url: string) => {
    throw new Error(`REDIRECT:${url}`);
  },
}));
vi.mock("@/lib/auth/session", () => session);
vi.mock("@/lib/api/server", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/server")>()),
  ...api,
}));

import { ApiError } from "@/lib/api/server";
import {
  createFirstGoalAction,
  saveAboutYouAction,
  saveStudyStyleAction,
  skipOnboardingAction,
} from "@/lib/onboarding/actions";
import { onboardingStepPath, parseOnboardingStep } from "@/lib/onboarding/paths";

const idle = { status: "idle" } as const;

function form(fields: Record<string, string | string[]>): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(fields)) {
    for (const item of Array.isArray(value) ? value : [value]) data.append(key, item);
  }
  return data;
}

beforeEach(() => {
  vi.clearAllMocks();
  session.getSessionUser.mockResolvedValue({ id: "u1", email: "a@b.c" });
  session.getAccessToken.mockResolvedValue("access-token-123");
});

describe("steps", () => {
  it.each([
    [undefined, 1],
    ["", 1],
    ["1", 1],
    ["2", 2],
    ["3", 3],
    ["4", 1],
    ["0", 1],
    ["-1", 1],
    ["abc", 1],
    ["2; drop table", 1],
  ])("reads ?step=%j as step %i", (value, step) => {
    expect(parseOnboardingStep(value)).toBe(step);
  });

  it("has a path for each step", () => {
    expect(onboardingStepPath(2)).toBe("/onboarding?step=2");
  });
});

describe("step 1: about you", () => {
  it("saves the name and languages, then moves on", async () => {
    api.updateMe.mockResolvedValue({});

    await expect(
      saveAboutYouAction(idle, form({ displayName: "Ada", languages: ["en", "or"] })),
    ).rejects.toThrow("REDIRECT:/onboarding?step=2");
    expect(api.updateMe).toHaveBeenCalledWith("access-token-123", {
      display_name: "Ada",
      preferred_languages: ["en", "or"],
    });
  });

  it("does not need a name", async () => {
    api.updateMe.mockResolvedValue({});

    await expect(
      saveAboutYouAction(idle, form({ displayName: "", languages: ["en"] })),
    ).rejects.toThrow("REDIRECT:/onboarding?step=2");
    expect(api.updateMe.mock.calls[0]?.[1]).toMatchObject({ display_name: null });
  });

  it("asks for at least one language, without calling the API", async () => {
    const state = await saveAboutYouAction(idle, form({ displayName: "Ada" }));

    expect(api.updateMe).not.toHaveBeenCalled();
    expect(state).toMatchObject({
      status: "error",
      fieldErrors: { languages: expect.any(String) },
    });
  });

  it("says nothing was saved when the service is down, and stays on the step", async () => {
    api.updateMe.mockRejectedValue(new ApiError(503, "SERVICE_UNAVAILABLE", "down"));

    const state = await saveAboutYouAction(idle, form({ displayName: "Ada", languages: ["en"] }));

    expect(state).toMatchObject({
      formError: expect.stringContaining("nothing was saved"),
      values: { displayName: "Ada" },
    });
  });

  it("returns to the same step after signing in again", async () => {
    api.updateMe.mockRejectedValue(new ApiError(401, "TOKEN_EXPIRED", "expired"));

    await expect(
      saveAboutYouAction(idle, form({ displayName: "", languages: ["en"] })),
    ).rejects.toThrow("REDIRECT:/sign-in?next=%2Fonboarding%3Fstep%3D1&error=session_ended");
  });
});

describe("step 2: how you like to study", () => {
  it("saves the study time and kinds of practice, then moves on", async () => {
    api.updateMe.mockResolvedValue({});

    await expect(
      saveStudyStyleAction(idle, form({ dailyMinutes: "45", learningPreferences: ["quizzes"] })),
    ).rejects.toThrow("REDIRECT:/onboarding?step=3");
    expect(api.updateMe).toHaveBeenCalledWith("access-token-123", {
      default_daily_minutes: 45,
      learning_preferences: ["quizzes"],
    });
  });

  it("accepts no kinds of practice at all", async () => {
    api.updateMe.mockResolvedValue({});

    await expect(saveStudyStyleAction(idle, form({ dailyMinutes: "45" }))).rejects.toThrow(
      "REDIRECT:/onboarding?step=3",
    );
    expect(api.updateMe.mock.calls[0]?.[1]).toMatchObject({ learning_preferences: [] });
  });

  it("rejects an impossible amount of time without calling the API", async () => {
    const state = await saveStudyStyleAction(idle, form({ dailyMinutes: "2000" }));

    expect(api.updateMe).not.toHaveBeenCalled();
    expect(state).toMatchObject({ fieldErrors: { dailyMinutes: expect.any(String) } });
  });
});

describe("step 3: the first goal", () => {
  const fields = {
    title: "Learn Docker",
    description: "",
    goalType: "certification",
    currentLevel: "unknown",
    targetDate: "",
  };

  it("creates the goal from the essentials, finishes onboarding and lands on the dashboard", async () => {
    api.createGoal.mockResolvedValue({ id: "g1" });
    api.completeOnboarding.mockResolvedValue({});

    await expect(createFirstGoalAction(idle, form(fields))).rejects.toThrow(
      "REDIRECT:/dashboard?notice=onboarded",
    );

    // No time, languages or practice are sent: the API fills them from the saved preferences.
    expect(api.createGoal).toHaveBeenCalledWith("access-token-123", {
      title: "Learn Docker",
      description: null,
      goal_type: "certification",
      current_level: "unknown",
      target_date: null,
    });
    expect(api.completeOnboarding).toHaveBeenCalledWith("access-token-123");
  });

  it("works without a target date and keeps one when given", async () => {
    api.createGoal.mockResolvedValue({ id: "g1" });
    api.completeOnboarding.mockResolvedValue({});

    await expect(
      createFirstGoalAction(idle, form({ ...fields, targetDate: "2027-05-01" })),
    ).rejects.toThrow("REDIRECT");

    expect(api.createGoal.mock.calls[0]?.[1]).toMatchObject({ target_date: "2027-05-01" });
  });

  it("does not finish onboarding if the goal could not be created", async () => {
    api.createGoal.mockRejectedValue(new ApiError(0, "API_UNREACHABLE", "down"));

    const state = await createFirstGoalAction(idle, form(fields));

    expect(api.completeOnboarding).not.toHaveBeenCalled();
    expect(state).toMatchObject({
      formError: expect.stringContaining("nothing was saved"),
      values: { title: "Learn Docker" },
    });
  });

  it("asks for a title, without calling the API", async () => {
    const state = await createFirstGoalAction(idle, form({ ...fields, title: " " }));

    expect(api.createGoal).not.toHaveBeenCalled();
    expect(state).toMatchObject({ fieldErrors: { title: expect.any(String) } });
  });

  it("never sends an owner", async () => {
    api.createGoal.mockResolvedValue({ id: "g1" });
    api.completeOnboarding.mockResolvedValue({});

    await expect(
      createFirstGoalAction(
        idle,
        form({ ...fields, user_id: "22222222-2222-4222-8222-222222222222" }),
      ),
    ).rejects.toThrow("REDIRECT");

    expect(Object.keys(api.createGoal.mock.calls[0]?.[1])).not.toContain("user_id");
  });
});

describe("skipping", () => {
  it("marks onboarding done without creating anything", async () => {
    api.completeOnboarding.mockResolvedValue({});

    await expect(skipOnboardingAction()).rejects.toThrow("REDIRECT:/dashboard?notice=skipped");
    expect(api.completeOnboarding).toHaveBeenCalledWith("access-token-123");
    expect(api.createGoal).not.toHaveBeenCalled();
    expect(api.updateMe).not.toHaveBeenCalled();
  });

  it("stays on onboarding with an explanation if it could not be recorded", async () => {
    api.completeOnboarding.mockRejectedValue(new ApiError(503, "SERVICE_UNAVAILABLE", "down"));

    await expect(skipOnboardingAction()).rejects.toThrow("REDIRECT:/onboarding?notice=unavailable");
  });

  it("sends a signed-out visitor to sign in", async () => {
    session.getSessionUser.mockResolvedValue(null);

    await expect(skipOnboardingAction()).rejects.toThrow("REDIRECT:/sign-in");
    expect(api.completeOnboarding).not.toHaveBeenCalled();
  });
});
