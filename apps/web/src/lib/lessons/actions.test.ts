// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest";

const session = vi.hoisted(() => ({
  getSessionUser: vi.fn(),
  getAccessToken: vi.fn(),
}));
const api = vi.hoisted(() => ({
  startLesson: vi.fn(),
  cancelJob: vi.fn(),
  retryJob: vi.fn(),
  saveLessonProgress: vi.fn(),
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
  cancelLessonAction,
  generateLessonAction,
  retryLessonAction,
  saveProgressAction,
} from "@/lib/lessons/actions";
import { GOAL, ITEM, JOB, LESSON } from "@/test-support/lessons";

const PAGE = `/goals/${GOAL}/learn/${ITEM}`;

function form(fields: Record<string, string> = {}): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(fields)) data.append(key, value);
  return data;
}

beforeEach(() => {
  vi.clearAllMocks();
  session.getSessionUser.mockResolvedValue({
    id: "11111111-1111-4111-8111-111111111111",
    email: "a@b.c",
  });
  session.getAccessToken.mockResolvedValue("access-token-123");
});

describe("generateLessonAction", () => {
  it("starts a lesson with the caller's token and goes back to the topic to follow it", async () => {
    api.startLesson.mockResolvedValue({ id: JOB });

    await expect(generateLessonAction(GOAL, ITEM, form())).rejects.toThrow(`REDIRECT:${PAGE}`);

    expect(api.startLesson).toHaveBeenCalledWith("access-token-123", ITEM, {
      adjust: null,
      feedback: null,
      regenerate: false,
    });
  });

  it("passes a known adjustment, a trimmed note and the regenerate flag", async () => {
    api.startLesson.mockResolvedValue({ id: JOB });

    await expect(
      generateLessonAction(
        GOAL,
        ITEM,
        form({ adjust: "simpler", feedback: "  use cooking  ", regenerate: "1" }),
      ),
    ).rejects.toThrow("REDIRECT");

    expect(api.startLesson).toHaveBeenCalledWith("access-token-123", ITEM, {
      adjust: "simpler",
      feedback: "use cooking",
      regenerate: true,
    });
  });

  it.each(["angrier", "", "SIMPLER", "simpler; drop table"])(
    "ignores the unknown adjustment %j",
    async (adjust) => {
      api.startLesson.mockResolvedValue({ id: JOB });

      await expect(generateLessonAction(GOAL, ITEM, form({ adjust }))).rejects.toThrow("REDIRECT");

      expect(api.startLesson.mock.calls[0]?.[2]).toMatchObject({ adjust: null });
    },
  );

  it("turns a blank note into none and never sends more than the API accepts", async () => {
    api.startLesson.mockResolvedValue({ id: JOB });

    await expect(generateLessonAction(GOAL, ITEM, form({ feedback: "   " }))).rejects.toThrow(
      "REDIRECT",
    );
    await expect(
      generateLessonAction(GOAL, ITEM, form({ feedback: "x".repeat(900) })),
    ).rejects.toThrow("REDIRECT");

    expect(api.startLesson.mock.calls[0]?.[2]).toMatchObject({ feedback: null });
    expect((api.startLesson.mock.calls[1]?.[2] as { feedback: string }).feedback).toHaveLength(300);
  });

  it("never sends an owner: only the token identifies the learner", async () => {
    api.startLesson.mockResolvedValue({ id: JOB });

    await expect(
      generateLessonAction(GOAL, ITEM, form({ user_id: "someone-else", goal_id: GOAL })),
    ).rejects.toThrow("REDIRECT");

    expect(Object.keys(api.startLesson.mock.calls[0]?.[2] as object).sort()).toEqual([
      "adjust",
      "feedback",
      "regenerate",
    ]);
  });

  it.each([
    ["LESSON_EXISTS", 409, "lesson-exists"],
    ["LESSON_QUEUE_FULL", 429, "lesson-queue-full"],
    ["LESSON_LIMIT_REACHED", 429, "lesson-limit"],
    ["AI_NOT_CONFIGURED", 503, "ai-unavailable"],
    ["GOAL_ARCHIVED", 409, "goal-archived"],
    ["ROADMAP_NOT_CURRENT", 409, "roadmap-not-current"],
    ["TOPIC_NOT_LESSONABLE", 422, "not-lessonable"],
    ["SOMETHING_ELSE", 409, "status-conflict"],
    ["API_UNREACHABLE", 0, "unavailable"],
  ])("explains a refusal with %s through a notice", async (code, status, notice) => {
    api.startLesson.mockRejectedValue(new ApiError(status, code, "refused"));

    await expect(generateLessonAction(GOAL, ITEM, form())).rejects.toThrow(
      `REDIRECT:${PAGE}?notice=${notice}`,
    );
  });

  it("shows a lesson that is already being written without a notice", async () => {
    api.startLesson.mockRejectedValue(new ApiError(409, "LESSON_JOB_ACTIVE", "busy"));

    await expect(generateLessonAction(GOAL, ITEM, form())).rejects.toThrow(`REDIRECT:${PAGE}`);
  });

  it("sends a refused session to sign-in rather than looping", async () => {
    api.startLesson.mockRejectedValue(new ApiError(401, "UNAUTHENTICATED", "no"));

    await expect(generateLessonAction(GOAL, ITEM, form())).rejects.toThrow(
      /REDIRECT:\/sign-in\?.*error=session_ended/,
    );
  });

  it("answers 404 with the not-found page, and a missing session with sign-in", async () => {
    api.startLesson.mockRejectedValue(new ApiError(404, "TOPIC_NOT_FOUND", "no"));
    await expect(generateLessonAction(GOAL, ITEM, form())).rejects.toThrow("NOT_FOUND");

    session.getSessionUser.mockResolvedValue(null);
    await expect(generateLessonAction(GOAL, ITEM, form())).rejects.toThrow(/REDIRECT:\/sign-in/);
  });

  it.each([
    ["../me", ITEM],
    [GOAL, "not-an-id"],
    [GOAL, "../../x"],
  ])("rejects the identifiers %j / %j before any API call", async (goal, item) => {
    await expect(generateLessonAction(goal, item, form())).rejects.toThrow("NOT_FOUND");

    expect(api.startLesson).not.toHaveBeenCalled();
  });

  it("does not hide an unexpected failure", async () => {
    api.startLesson.mockRejectedValue(new TypeError("boom"));

    await expect(generateLessonAction(GOAL, ITEM, form())).rejects.toThrow("boom");
  });
});

describe("cancelLessonAction and retryLessonAction", () => {
  it("cancels the job and tells the learner nothing was saved", async () => {
    api.cancelJob.mockResolvedValue({});

    await expect(cancelLessonAction(GOAL, ITEM, JOB)).rejects.toThrow(
      `REDIRECT:${PAGE}?notice=lesson-cancelled`,
    );

    expect(api.cancelJob).toHaveBeenCalledWith("access-token-123", JOB);
  });

  it("retries a failed job and follows the new one", async () => {
    api.retryJob.mockResolvedValue({ id: JOB });

    await expect(retryLessonAction(GOAL, ITEM, JOB)).rejects.toThrow(`REDIRECT:${PAGE}`);

    expect(api.retryJob).toHaveBeenCalledWith("access-token-123", JOB);
  });

  it("explains why a retry was refused", async () => {
    api.retryJob.mockRejectedValue(new ApiError(429, "LESSON_LIMIT_REACHED", "limit"));

    await expect(retryLessonAction(GOAL, ITEM, JOB)).rejects.toThrow(
      `REDIRECT:${PAGE}?notice=lesson-limit`,
    );
  });

  it("rejects crafted identifiers and another learner's job (404)", async () => {
    await expect(cancelLessonAction(GOAL, ITEM, "../x")).rejects.toThrow("NOT_FOUND");
    expect(api.cancelJob).not.toHaveBeenCalled();

    api.retryJob.mockRejectedValue(new ApiError(404, "JOB_NOT_FOUND", "no"));
    await expect(retryLessonAction(GOAL, ITEM, JOB)).rejects.toThrow("NOT_FOUND");
  });
});

describe("saveProgressAction", () => {
  const input = {
    completedSectionIds: ["s2", "s1", "s2"],
    currentSectionId: "s2",
    completed: false,
  };

  it("saves the learner's place and reports success", async () => {
    api.saveLessonProgress.mockResolvedValue({});

    const result = await saveProgressAction(GOAL, ITEM, LESSON, input);

    expect(result).toEqual({ ok: true });
    expect(api.saveLessonProgress).toHaveBeenCalledWith("access-token-123", LESSON, {
      completed_section_ids: ["s2", "s1"],
      current_section_id: "s2",
      completed: false,
    });
  });

  it("drops anything that is not a section id before it reaches the API", async () => {
    api.saveLessonProgress.mockResolvedValue({});

    await saveProgressAction(GOAL, ITEM, LESSON, {
      completedSectionIds: ["s1", "../x", "S2", "s123", "<b>"],
      currentSectionId: "intro",
      completed: true,
    });

    expect(api.saveLessonProgress).toHaveBeenCalledWith("access-token-123", LESSON, {
      completed_section_ids: ["s1"],
      current_section_id: null,
      completed: true,
    });
  });

  it("never sends more sections than a lesson can have", async () => {
    api.saveLessonProgress.mockResolvedValue({});
    const many = Array.from({ length: 40 }, (_, n) => `s${n + 1}`);

    await saveProgressAction(GOAL, ITEM, LESSON, {
      completedSectionIds: many,
      currentSectionId: null,
      completed: false,
    });

    const body = api.saveLessonProgress.mock.calls[0]?.[2] as { completed_section_ids: string[] };
    expect(body.completed_section_ids).toHaveLength(12);
  });

  it("reports a failure instead of throwing the learner out of the lesson", async () => {
    api.saveLessonProgress.mockRejectedValueOnce(new ApiError(401, "UNAUTHENTICATED", "no"));
    api.saveLessonProgress.mockRejectedValueOnce(new ApiError(409, "GOAL_ARCHIVED", "no"));
    api.saveLessonProgress.mockRejectedValueOnce(new ApiError(0, "API_UNREACHABLE", "down"));
    api.saveLessonProgress.mockRejectedValueOnce(new ApiError(422, "UNKNOWN_SECTION", "bad"));

    expect(await saveProgressAction(GOAL, ITEM, LESSON, input)).toEqual({
      ok: false,
      reason: "session",
    });
    expect(await saveProgressAction(GOAL, ITEM, LESSON, input)).toEqual({
      ok: false,
      reason: "archived",
    });
    expect(await saveProgressAction(GOAL, ITEM, LESSON, input)).toEqual({
      ok: false,
      reason: "unavailable",
    });
    expect(await saveProgressAction(GOAL, ITEM, LESSON, input)).toEqual({
      ok: false,
      reason: "unavailable",
    });
  });

  it("answers 404 with the not-found page and rejects crafted identifiers", async () => {
    api.saveLessonProgress.mockRejectedValue(new ApiError(404, "LESSON_NOT_FOUND", "no"));
    await expect(saveProgressAction(GOAL, ITEM, LESSON, input)).rejects.toThrow("NOT_FOUND");

    await expect(saveProgressAction(GOAL, ITEM, "../x", input)).rejects.toThrow("NOT_FOUND");
  });

  it("needs a signed-in learner", async () => {
    session.getSessionUser.mockResolvedValue(null);

    await expect(saveProgressAction(GOAL, ITEM, LESSON, input)).rejects.toThrow(
      /REDIRECT:\/sign-in/,
    );
    expect(api.saveLessonProgress).not.toHaveBeenCalled();
  });
});
