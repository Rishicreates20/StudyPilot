// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest";

const session = vi.hoisted(() => ({
  getSessionUser: vi.fn(),
  getAccessToken: vi.fn(),
}));
const api = vi.hoisted(() => ({ createGoal: vi.fn() }));

vi.mock("next/navigation", () => ({
  redirect: (url: string) => {
    throw new Error(`REDIRECT:${url}`);
  },
}));
vi.mock("@/lib/auth/session", () => session);
vi.mock("@/lib/api/server", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/server")>()),
  createGoal: api.createGoal,
}));

import { ApiError } from "@/lib/api/server";
import { createGoalAction } from "@/lib/goals/actions";

const idle = { status: "idle" } as const;

function form(fields: Record<string, string | string[]>): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(fields)) {
    for (const item of Array.isArray(value) ? value : [value]) data.append(key, item);
  }
  return data;
}

const validFields = {
  title: "Learn Kubernetes",
  description: "",
  goalType: "interview",
  currentLevel: "beginner",
  targetDate: "2027-01-31",
  dailyMinutes: "90",
  languages: ["en", "hi"],
};

beforeEach(() => {
  vi.clearAllMocks();
  session.getSessionUser.mockResolvedValue({
    id: "11111111-1111-4111-8111-111111111111",
    email: "a@b.c",
  });
  session.getAccessToken.mockResolvedValue("access-token-123");
});

describe("createGoalAction", () => {
  it("creates the goal with the caller's token and returns to the dashboard", async () => {
    api.createGoal.mockResolvedValue({ id: "g1" });

    await expect(createGoalAction(idle, form(validFields))).rejects.toThrow(
      "REDIRECT:/dashboard?created=1",
    );
    expect(api.createGoal).toHaveBeenCalledWith("access-token-123", {
      title: "Learn Kubernetes",
      description: null,
      goal_type: "interview",
      current_level: "beginner",
      target_date: "2027-01-31",
      daily_minutes: 90,
      preferred_languages: ["en", "hi"],
    });
  });

  it("never sends an owner: identity is the token's job", async () => {
    api.createGoal.mockResolvedValue({ id: "g1" });
    // A tampered form that tries to name another user.
    const tampered = form({
      ...validFields,
      user_id: "22222222-2222-4222-8222-222222222222",
      userId: "x",
    });

    await expect(createGoalAction(idle, tampered)).rejects.toThrow("REDIRECT");

    const payload = api.createGoal.mock.calls[0]?.[1];
    expect(Object.keys(payload)).not.toContain("user_id");
    expect(JSON.stringify(payload)).not.toContain("22222222");
  });

  it("returns field errors and the typed values without calling the API when input is invalid", async () => {
    const state = await createGoalAction(
      idle,
      form({ ...validFields, title: "", dailyMinutes: "5", languages: [] }),
    );

    expect(api.createGoal).not.toHaveBeenCalled();
    expect(state).toMatchObject({
      status: "error",
      fieldErrors: {
        title: expect.any(String),
        dailyMinutes: expect.any(String),
        languages: expect.any(String),
      },
      values: { dailyMinutes: "5", goalType: "interview" },
    });
  });

  it("sends a signed-out visitor to sign in, returning to the form afterwards", async () => {
    session.getSessionUser.mockResolvedValue(null);

    await expect(createGoalAction(idle, form(validFields))).rejects.toThrow(
      "REDIRECT:/sign-in?next=%2Fgoals%2Fnew",
    );
    expect(api.createGoal).not.toHaveBeenCalled();
  });

  it("treats a missing access token the same way", async () => {
    session.getAccessToken.mockResolvedValue(null);

    await expect(createGoalAction(idle, form(validFields))).rejects.toThrow("REDIRECT:/sign-in");
  });

  it("asks the user to sign in again when the API rejects a session Supabase still holds", async () => {
    api.createGoal.mockRejectedValue(new ApiError(401, "TOKEN_EXPIRED", "expired"));

    // The marker tells the sign-in page to show its form instead of bouncing a visitor who still
    // has a (now useless) session cookie straight back here, which would loop.
    await expect(createGoalAction(idle, form(validFields))).rejects.toThrow(
      "REDIRECT:/sign-in?next=%2Fgoals%2Fnew&error=session_ended",
    );
  });

  it("shows the API's field-level validation next to the right inputs", async () => {
    api.createGoal.mockRejectedValue(
      new ApiError(422, "VALIDATION_ERROR", "invalid", {
        fieldErrors: { target_date: "The target date can't be in the past." },
      }),
    );

    const state = await createGoalAction(idle, form(validFields));

    expect(state).toMatchObject({
      status: "error",
      fieldErrors: { targetDate: "The target date can't be in the past." },
    });
  });

  it("explains the goal limit using the API's own wording", async () => {
    api.createGoal.mockRejectedValue(
      new ApiError(409, "GOAL_LIMIT_REACHED", "You can have up to 50 goals at once."),
    );

    const state = await createGoalAction(idle, form(validFields));

    expect(state).toMatchObject({ formError: "You can have up to 50 goals at once." });
  });

  it.each([0, 503])(
    "reassures the user that nothing was saved when the service is down (%i)",
    async (status) => {
      api.createGoal.mockRejectedValue(new ApiError(status, "SERVICE_UNAVAILABLE", "down"));

      const state = await createGoalAction(idle, form(validFields));

      expect(state).toMatchObject({
        status: "error",
        formError: expect.stringContaining("was not saved"),
        values: { title: "Learn Kubernetes" },
      });
    },
  );

  it("offers a reference for unexpected API failures", async () => {
    api.createGoal.mockRejectedValue(
      new ApiError(500, "INTERNAL_ERROR", "boom", { requestId: "req-abc-123" }),
    );

    const state = await createGoalAction(idle, form(validFields));

    expect(state).toMatchObject({ formError: expect.stringContaining("req-abc-123") });
  });

  it("does not swallow genuine programming errors", async () => {
    api.createGoal.mockRejectedValue(new TypeError("bug"));

    await expect(createGoalAction(idle, form(validFields))).rejects.toThrow("bug");
  });
});
