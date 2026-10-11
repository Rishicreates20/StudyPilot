// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest";

const session = vi.hoisted(() => ({
  getSessionUser: vi.fn(),
  getAccessToken: vi.fn(),
}));
const api = vi.hoisted(() => ({
  createGoal: vi.fn(),
  updateGoal: vi.fn(),
  setGoalStatus: vi.fn(),
  deleteGoal: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  redirect: (url: string) => {
    throw new Error(`REDIRECT:${url}`);
  },
  notFound: () => {
    throw new Error("NOT_FOUND");
  },
}));
vi.mock("@/lib/auth/session", () => session);
vi.mock("@/lib/api/server", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/server")>()),
  ...api,
}));

import { ApiError } from "@/lib/api/server";
import {
  changeGoalStatusAction,
  createGoalAction,
  deleteGoalAction,
  updateGoalAction,
} from "@/lib/goals/actions";

const idle = { status: "idle" } as const;
const GOAL_ID = "33333333-3333-4333-8333-333333333333";

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
  learningPreferences: ["examples", "quizzes"],
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
      "REDIRECT:/dashboard?notice=created",
    );
    expect(api.createGoal).toHaveBeenCalledWith("access-token-123", {
      title: "Learn Kubernetes",
      description: null,
      goal_type: "interview",
      current_level: "beginner",
      target_date: "2027-01-31",
      daily_minutes: 90,
      preferred_languages: ["en", "hi"],
      learning_preferences: ["examples", "quizzes"],
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
        fieldErrors: {
          target_date: "The target date can't be in the past.",
          learning_preferences: "Pick from the list.",
        },
      }),
    );

    const state = await createGoalAction(idle, form(validFields));

    expect(state).toMatchObject({
      status: "error",
      fieldErrors: {
        targetDate: "The target date can't be in the past.",
        learningPreferences: "Pick from the list.",
      },
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
        formError: expect.stringContaining("nothing was saved"),
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

describe("updateGoalAction", () => {
  it("saves every field and returns to the goal with a confirmation", async () => {
    api.updateGoal.mockResolvedValue({ id: GOAL_ID });

    await expect(updateGoalAction(GOAL_ID, idle, form(validFields))).rejects.toThrow(
      `REDIRECT:/goals/${GOAL_ID}?notice=updated`,
    );
    expect(api.updateGoal).toHaveBeenCalledWith("access-token-123", GOAL_ID, {
      title: "Learn Kubernetes",
      description: null,
      goal_type: "interview",
      current_level: "beginner",
      target_date: "2027-01-31",
      daily_minutes: 90,
      preferred_languages: ["en", "hi"],
      learning_preferences: ["examples", "quizzes"],
    });
  });

  it("clears the target date and notes when the fields are emptied", async () => {
    api.updateGoal.mockResolvedValue({ id: GOAL_ID });

    await expect(
      updateGoalAction(GOAL_ID, idle, form({ ...validFields, targetDate: "", description: " " })),
    ).rejects.toThrow("REDIRECT");

    expect(api.updateGoal.mock.calls[0]?.[2]).toMatchObject({
      description: null,
      target_date: null,
    });
  });

  it("never sends an owner or a status", async () => {
    api.updateGoal.mockResolvedValue({ id: GOAL_ID });
    const tampered = form({
      ...validFields,
      user_id: "22222222-2222-4222-8222-222222222222",
      status: "archived",
    });

    await expect(updateGoalAction(GOAL_ID, idle, tampered)).rejects.toThrow("REDIRECT");

    const body = api.updateGoal.mock.calls[0]?.[2];
    expect(Object.keys(body)).not.toContain("user_id");
    expect(Object.keys(body)).not.toContain("status");
  });

  it.each(["not-a-uuid", "../me", "", "33333333-3333-4333-8333-33333333333"])(
    "refuses the goal ID %j without calling the API",
    async (badId) => {
      await expect(updateGoalAction(badId, idle, form(validFields))).rejects.toThrow("NOT_FOUND");
      expect(api.updateGoal).not.toHaveBeenCalled();
    },
  );

  it("returns field errors without calling the API when the input is invalid", async () => {
    const state = await updateGoalAction(GOAL_ID, idle, form({ ...validFields, title: "" }));

    expect(api.updateGoal).not.toHaveBeenCalled();
    expect(state).toMatchObject({ status: "error", fieldErrors: { title: expect.any(String) } });
  });

  it("sends a signed-out visitor to sign in and back to the edit page", async () => {
    session.getSessionUser.mockResolvedValue(null);

    await expect(updateGoalAction(GOAL_ID, idle, form(validFields))).rejects.toThrow(
      `REDIRECT:/sign-in?next=%2Fgoals%2F${GOAL_ID}%2Fedit`,
    );
  });

  it("shows the not-found page when the goal isn't the caller's", async () => {
    api.updateGoal.mockRejectedValue(new ApiError(404, "GOAL_NOT_FOUND", "Goal not found."));

    await expect(updateGoalAction(GOAL_ID, idle, form(validFields))).rejects.toThrow("NOT_FOUND");
  });

  it("asks the user to sign in again when the API rejects the session", async () => {
    api.updateGoal.mockRejectedValue(new ApiError(401, "TOKEN_EXPIRED", "expired"));

    await expect(updateGoalAction(GOAL_ID, idle, form(validFields))).rejects.toThrow(
      `error=session_ended`,
    );
  });

  it("explains that an archived goal must be restored first, in the API's words", async () => {
    api.updateGoal.mockRejectedValue(
      new ApiError(409, "GOAL_ARCHIVED", "This goal is archived. Restore it before editing it."),
    );

    const state = await updateGoalAction(GOAL_ID, idle, form(validFields));

    expect(state).toMatchObject({
      status: "error",
      formError: "This goal is archived. Restore it before editing it.",
      values: { title: "Learn Kubernetes" },
    });
  });

  it("maps the API's field errors onto the form and keeps what was typed", async () => {
    api.updateGoal.mockRejectedValue(
      new ApiError(422, "VALIDATION_ERROR", "invalid", {
        fieldErrors: { target_date: "The target date can't be in the past." },
      }),
    );

    const state = await updateGoalAction(GOAL_ID, idle, form(validFields));

    expect(state).toMatchObject({
      fieldErrors: { targetDate: "The target date can't be in the past." },
      values: { dailyMinutes: "90" },
    });
  });

  it("says nothing was saved when the service is down", async () => {
    api.updateGoal.mockRejectedValue(new ApiError(0, "API_UNREACHABLE", "down"));

    const state = await updateGoalAction(GOAL_ID, idle, form(validFields));

    expect(state).toMatchObject({ formError: expect.stringContaining("nothing was saved") });
  });
});

describe("changeGoalStatusAction", () => {
  it.each(["paused", "active", "completed"] as const)(
    "moves the goal to %s and stays on it with a confirmation",
    async (target) => {
      api.setGoalStatus.mockResolvedValue({ id: GOAL_ID });

      await expect(changeGoalStatusAction(GOAL_ID, target)).rejects.toThrow(
        `REDIRECT:/goals/${GOAL_ID}?notice=${target}`,
      );
      expect(api.setGoalStatus).toHaveBeenCalledWith("access-token-123", GOAL_ID, target);
    },
  );

  it("archiving returns to the dashboard, because the goal has left it", async () => {
    api.setGoalStatus.mockResolvedValue({ id: GOAL_ID });

    await expect(changeGoalStatusAction(GOAL_ID, "archived")).rejects.toThrow(
      "REDIRECT:/dashboard?notice=archived",
    );
  });

  it.each([
    ["not-a-uuid", "paused"],
    [GOAL_ID, "deleted"],
    [GOAL_ID, ""],
    [GOAL_ID, "__proto__"],
  ])("refuses goal %j with status %j without calling the API", async (goalId, target) => {
    await expect(changeGoalStatusAction(goalId, target)).rejects.toThrow("NOT_FOUND");
    expect(api.setGoalStatus).not.toHaveBeenCalled();
  });

  it("sends a signed-out visitor to sign in", async () => {
    session.getSessionUser.mockResolvedValue(null);

    await expect(changeGoalStatusAction(GOAL_ID, "paused")).rejects.toThrow(
      `REDIRECT:/sign-in?next=%2Fgoals%2F${GOAL_ID}`,
    );
    expect(api.setGoalStatus).not.toHaveBeenCalled();
  });

  it("shows the not-found page for a goal that isn't the caller's", async () => {
    api.setGoalStatus.mockRejectedValue(new ApiError(404, "GOAL_NOT_FOUND", "Goal not found."));

    await expect(changeGoalStatusAction(GOAL_ID, "paused")).rejects.toThrow("NOT_FOUND");
  });

  it("asks the user to sign in again when the API rejects the session", async () => {
    api.setGoalStatus.mockRejectedValue(new ApiError(401, "TOKEN_EXPIRED", "expired"));

    await expect(changeGoalStatusAction(GOAL_ID, "paused")).rejects.toThrow("error=session_ended");
  });

  it.each([
    [new ApiError(409, "INVALID_STATUS_TRANSITION", "no"), "status-conflict"],
    [new ApiError(409, "GOAL_LIMIT_REACHED", "full"), "limit-reached"],
    [new ApiError(503, "SERVICE_UNAVAILABLE", "down"), "unavailable"],
    [new ApiError(0, "API_UNREACHABLE", "down"), "unavailable"],
  ])("explains a refusal on the goal's own page (%#)", async (error, notice) => {
    api.setGoalStatus.mockRejectedValue(error);

    await expect(changeGoalStatusAction(GOAL_ID, "active")).rejects.toThrow(
      `REDIRECT:/goals/${GOAL_ID}?notice=${notice}`,
    );
  });

  it("does not swallow genuine programming errors", async () => {
    api.setGoalStatus.mockRejectedValue(new TypeError("bug"));

    await expect(changeGoalStatusAction(GOAL_ID, "paused")).rejects.toThrow("bug");
  });
});

describe("deleteGoalAction", () => {
  it("deletes the goal and returns to the archive with a confirmation", async () => {
    api.deleteGoal.mockResolvedValue(undefined);

    await expect(deleteGoalAction(GOAL_ID)).rejects.toThrow(
      "REDIRECT:/goals/archived?notice=deleted",
    );
    expect(api.deleteGoal).toHaveBeenCalledWith("access-token-123", GOAL_ID);
  });

  it.each(["not-a-uuid", "../me", ""])(
    "refuses the goal ID %j without calling the API",
    async (id) => {
      await expect(deleteGoalAction(id)).rejects.toThrow("NOT_FOUND");
      expect(api.deleteGoal).not.toHaveBeenCalled();
    },
  );

  it("explains that only archived goals can be deleted", async () => {
    api.deleteGoal.mockRejectedValue(new ApiError(409, "GOAL_NOT_ARCHIVED", "Archive it first."));

    await expect(deleteGoalAction(GOAL_ID)).rejects.toThrow(
      `REDIRECT:/goals/${GOAL_ID}?notice=not-archived`,
    );
  });

  it("shows the not-found page for a goal that isn't the caller's", async () => {
    api.deleteGoal.mockRejectedValue(new ApiError(404, "GOAL_NOT_FOUND", "Goal not found."));

    await expect(deleteGoalAction(GOAL_ID)).rejects.toThrow("NOT_FOUND");
  });

  it("sends a signed-out visitor to sign in", async () => {
    session.getAccessToken.mockResolvedValue(null);

    await expect(deleteGoalAction(GOAL_ID)).rejects.toThrow("REDIRECT:/sign-in");
    expect(api.deleteGoal).not.toHaveBeenCalled();
  });
});
