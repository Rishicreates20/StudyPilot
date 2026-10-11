// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest";

const session = vi.hoisted(() => ({ getSessionUser: vi.fn(), getAccessToken: vi.fn() }));
const api = vi.hoisted(() => ({ updateMe: vi.fn() }));
const cache = vi.hoisted(() => ({ revalidatePath: vi.fn() }));

vi.mock("next/navigation", () => ({
  redirect: (url: string) => {
    throw new Error(`REDIRECT:${url}`);
  },
}));
vi.mock("next/cache", () => cache);
vi.mock("@/lib/auth/session", () => session);
vi.mock("@/lib/api/server", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/server")>()),
  ...api,
}));

import { ApiError, type Me } from "@/lib/api/server";
import { saveSettingsAction } from "@/lib/profile/actions";
import {
  aboutYouSchema,
  mapApiSettingsErrors,
  meToSettingsValues,
  readSettingsValues,
  settingsSchema,
  studyStyleSchema,
} from "@/lib/profile/schema";

const idle = { status: "idle" } as const;

function form(fields: Record<string, string | string[]>): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(fields)) {
    for (const item of Array.isArray(value) ? value : [value]) data.append(key, item);
  }
  return data;
}

const validFields = {
  displayName: "Ada Lovelace",
  timezone: "Asia/Kolkata",
  dailyMinutes: "75",
  languages: ["en", "hi"],
  learningPreferences: ["quizzes"],
};

beforeEach(() => {
  vi.clearAllMocks();
  session.getSessionUser.mockResolvedValue({ id: "u1", email: "a@b.c" });
  session.getAccessToken.mockResolvedValue("access-token-123");
});

describe("settingsSchema", () => {
  it("accepts a complete, valid set of settings", () => {
    const result = settingsSchema.safeParse(validFields);

    expect(result.success && result.data.dailyMinutes).toBe(75);
  });

  it("lets the name be left blank", () => {
    expect(settingsSchema.safeParse({ ...validFields, displayName: "" }).success).toBe(true);
  });

  it.each([
    [{ displayName: "n".repeat(81) }, "displayName"],
    [{ timezone: "" }, "timezone"],
    [{ dailyMinutes: "9" }, "dailyMinutes"],
    [{ dailyMinutes: "481" }, "dailyMinutes"],
    [{ languages: [] }, "languages"],
    [{ languages: ["fr"] }, "languages"],
    [{ learningPreferences: ["flashcards"] }, "learningPreferences"],
  ])("rejects %j", (override, field) => {
    const result = settingsSchema.safeParse({ ...validFields, ...override });

    expect(result.success).toBe(false);
    if (!result.success) expect(result.error.issues.map((i) => i.path[0])).toContain(field);
  });

  it("splits into the two onboarding steps", () => {
    expect(aboutYouSchema.safeParse({ displayName: "", languages: ["en"] }).success).toBe(true);
    expect(aboutYouSchema.safeParse({ displayName: "", languages: [] }).success).toBe(false);
    expect(
      studyStyleSchema.safeParse({ dailyMinutes: "30", learningPreferences: [] }).success,
    ).toBe(true);
    expect(studyStyleSchema.safeParse({ dailyMinutes: "1", learningPreferences: [] }).success).toBe(
      false,
    );
  });
});

describe("settings values", () => {
  const me: Me = {
    id: "11111111-1111-4111-8111-111111111111",
    email: "ada@example.com",
    display_name: null,
    locale: "en",
    timezone: "Europe/London",
    onboarding_completed: true,
    preferences: {
      default_daily_minutes: 20,
      preferred_languages: ["or"],
      learning_preferences: [],
    },
    created_at: "2026-10-09T00:00:00Z",
  };

  it("turns the saved profile into form values", () => {
    expect(meToSettingsValues(me)).toEqual({
      displayName: "",
      timezone: "Europe/London",
      dailyMinutes: "20",
      languages: ["or"],
      learningPreferences: [],
    });
  });

  it("reads a submission, keeping repeated checkboxes and ignoring unknown fields", () => {
    const values = readSettingsValues(
      form({ ...validFields, user_id: "22222222-2222-4222-8222-222222222222" }),
    );

    expect(values).toEqual(validFields);
  });

  it("maps the API's field names to the form's", () => {
    expect(
      mapApiSettingsErrors({
        display_name: "a",
        timezone: "b",
        default_daily_minutes: "c",
        preferred_languages: "d",
        learning_preferences: "e",
        id: "ignored",
      }),
    ).toEqual({
      displayName: "a",
      timezone: "b",
      dailyMinutes: "c",
      languages: "d",
      learningPreferences: "e",
    });
  });
});

describe("saveSettingsAction", () => {
  it("saves the preferences and says so, returning what was saved", async () => {
    api.updateMe.mockResolvedValue({});

    const state = await saveSettingsAction(idle, form(validFields));

    expect(api.updateMe).toHaveBeenCalledWith("access-token-123", {
      display_name: "Ada Lovelace",
      timezone: "Asia/Kolkata",
      default_daily_minutes: 75,
      preferred_languages: ["en", "hi"],
      learning_preferences: ["quizzes"],
    });
    expect(state).toEqual({
      status: "success",
      message: "Your preferences are saved.",
      values: { ...validFields, dailyMinutes: "75" },
    });
    expect(cache.revalidatePath).toHaveBeenCalledWith("/settings");
  });

  it("clears the name when it is emptied", async () => {
    api.updateMe.mockResolvedValue({});

    await saveSettingsAction(idle, form({ ...validFields, displayName: "  " }));

    expect(api.updateMe.mock.calls[0]?.[1]).toMatchObject({ display_name: null });
  });

  it("never sends an owner or identity fields", async () => {
    api.updateMe.mockResolvedValue({});

    await saveSettingsAction(
      idle,
      form({ ...validFields, id: "22222222-2222-4222-8222-222222222222", email: "x@y.z" }),
    );

    const body = api.updateMe.mock.calls[0]?.[1];
    expect(Object.keys(body).sort()).toEqual([
      "default_daily_minutes",
      "display_name",
      "learning_preferences",
      "preferred_languages",
      "timezone",
    ]);
  });

  it("returns field errors without calling the API when the input is invalid", async () => {
    const state = await saveSettingsAction(idle, form({ ...validFields, dailyMinutes: "5" }));

    expect(api.updateMe).not.toHaveBeenCalled();
    expect(state).toMatchObject({
      status: "error",
      fieldErrors: { dailyMinutes: expect.any(String) },
      values: { dailyMinutes: "5" },
    });
    expect(cache.revalidatePath).not.toHaveBeenCalled();
  });

  it("maps the API's validation errors onto the fields", async () => {
    api.updateMe.mockRejectedValue(
      new ApiError(422, "VALIDATION_ERROR", "invalid", {
        fieldErrors: { timezone: "Choose a timezone from the list." },
      }),
    );

    const state = await saveSettingsAction(idle, form(validFields));

    expect(state).toMatchObject({
      status: "error",
      fieldErrors: { timezone: "Choose a timezone from the list." },
    });
  });

  it("says nothing was saved when the service is down, and keeps the answers", async () => {
    api.updateMe.mockRejectedValue(new ApiError(0, "API_UNREACHABLE", "down"));

    const state = await saveSettingsAction(idle, form(validFields));

    expect(state).toMatchObject({
      formError: expect.stringContaining("nothing was saved"),
      values: { displayName: "Ada Lovelace" },
    });
  });

  it("sends a signed-out visitor to sign in", async () => {
    session.getSessionUser.mockResolvedValue(null);

    await expect(saveSettingsAction(idle, form(validFields))).rejects.toThrow(
      "REDIRECT:/sign-in?next=%2Fsettings",
    );
    expect(api.updateMe).not.toHaveBeenCalled();
  });

  it("asks the user to sign in again when the API rejects the session", async () => {
    api.updateMe.mockRejectedValue(new ApiError(401, "TOKEN_EXPIRED", "expired"));

    await expect(saveSettingsAction(idle, form(validFields))).rejects.toThrow(
      "REDIRECT:/sign-in?next=%2Fsettings&error=session_ended",
    );
  });

  it("does not swallow genuine programming errors", async () => {
    api.updateMe.mockRejectedValue(new TypeError("bug"));

    await expect(saveSettingsAction(idle, form(validFields))).rejects.toThrow("bug");
  });
});
