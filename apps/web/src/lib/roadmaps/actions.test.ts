// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest";

const session = vi.hoisted(() => ({
  getSessionUser: vi.fn(),
  getAccessToken: vi.fn(),
}));
const api = vi.hoisted(() => ({
  startRoadmap: vi.fn(),
  cancelJob: vi.fn(),
  retryJob: vi.fn(),
  makeRoadmapCurrent: vi.fn(),
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
  cancelGenerationAction,
  generateRoadmapAction,
  makeRoadmapCurrentAction,
  retryGenerationAction,
} from "@/lib/roadmaps/actions";

const GOAL_ID = "33333333-3333-4333-8333-333333333333";
const JOB_ID = "44444444-4444-4444-8444-444444444444";
const ROADMAP_ID = "55555555-5555-4555-8555-555555555555";
const GOAL_PAGE = `/goals/${GOAL_ID}`;

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

describe("generateRoadmapAction", () => {
  it("starts a generation with the caller's token and goes back to the goal to follow it", async () => {
    api.startRoadmap.mockResolvedValue({ id: JOB_ID });

    await expect(generateRoadmapAction(GOAL_ID, form())).rejects.toThrow(`REDIRECT:${GOAL_PAGE}`);

    expect(api.startRoadmap).toHaveBeenCalledWith("access-token-123", GOAL_ID, { feedback: null });
  });

  it("passes a trimmed revision note", async () => {
    api.startRoadmap.mockResolvedValue({ id: JOB_ID });

    await expect(
      generateRoadmapAction(GOAL_ID, form({ feedback: "  fewer topics  " })),
    ).rejects.toThrow("REDIRECT");

    expect(api.startRoadmap).toHaveBeenCalledWith("access-token-123", GOAL_ID, {
      feedback: "fewer topics",
    });
  });

  it("turns a blank note into none and never sends more than the API accepts", async () => {
    api.startRoadmap.mockResolvedValue({ id: JOB_ID });

    await expect(generateRoadmapAction(GOAL_ID, form({ feedback: "   " }))).rejects.toThrow();
    await expect(
      generateRoadmapAction(GOAL_ID, form({ feedback: "x".repeat(900) })),
    ).rejects.toThrow();

    expect(api.startRoadmap.mock.calls[0]?.[2]).toEqual({ feedback: null });
    expect(api.startRoadmap.mock.calls[1]?.[2]?.feedback).toHaveLength(500);
  });

  it("never sends an owner: a tampered form cannot name another user", async () => {
    api.startRoadmap.mockResolvedValue({ id: JOB_ID });
    const tampered = form({ feedback: "ok", user_id: "22222222-2222-4222-8222-222222222222" });

    await expect(generateRoadmapAction(GOAL_ID, tampered)).rejects.toThrow("REDIRECT");

    expect(JSON.stringify(api.startRoadmap.mock.calls)).not.toContain("22222222");
  });

  it("refuses an id that is not a goal id before calling the API", async () => {
    await expect(generateRoadmapAction("../me", form())).rejects.toThrow("NOT_FOUND");

    expect(api.startRoadmap).not.toHaveBeenCalled();
  });

  it("sends a signed-out visitor to sign in", async () => {
    session.getSessionUser.mockResolvedValue(null);

    await expect(generateRoadmapAction(GOAL_ID, form())).rejects.toThrow("REDIRECT:/sign-in");

    expect(api.startRoadmap).not.toHaveBeenCalled();
  });

  it("ends the session when the API rejects the token", async () => {
    api.startRoadmap.mockRejectedValue(new ApiError(401, "INVALID_TOKEN", "no"));

    await expect(generateRoadmapAction(GOAL_ID, form())).rejects.toThrow(
      /REDIRECT:\/sign-in.*session_ended/,
    );
  });

  it("answers 404 for a goal that is not the caller's", async () => {
    api.startRoadmap.mockRejectedValue(new ApiError(404, "GOAL_NOT_FOUND", "no"));

    await expect(generateRoadmapAction(GOAL_ID, form())).rejects.toThrow("NOT_FOUND");
  });

  it.each([
    [409, "ROADMAP_JOB_ACTIVE", "already-generating"],
    [422, "GOAL_NOT_PLANNABLE", "needs-detail"],
    [503, "AI_NOT_CONFIGURED", "ai-unavailable"],
    [429, "GENERATION_LIMIT_REACHED", "generation-limit"],
    [409, "GOAL_ARCHIVED", "goal-archived"],
    [409, "SOMETHING_ELSE", "status-conflict"],
    [500, "INTERNAL_ERROR", "unavailable"],
    [0, "API_UNREACHABLE", "unavailable"],
  ])("explains a %d %s refusal with the '%s' notice", async (status, code, notice) => {
    api.startRoadmap.mockRejectedValue(new ApiError(status, code, "internal text"));

    await expect(generateRoadmapAction(GOAL_ID, form())).rejects.toThrow(
      `REDIRECT:${GOAL_PAGE}?notice=${notice}`,
    );
  });

  it("never puts the API's own message into the URL", async () => {
    api.startRoadmap.mockRejectedValue(
      new ApiError(409, "ROADMAP_JOB_ACTIVE", "SECRET internal text"),
    );

    await expect(generateRoadmapAction(GOAL_ID, form())).rejects.toThrow(
      expect.not.objectContaining({ message: expect.stringContaining("SECRET") }),
    );
  });

  it("lets unexpected errors surface instead of hiding them", async () => {
    api.startRoadmap.mockRejectedValue(new TypeError("bug"));

    await expect(generateRoadmapAction(GOAL_ID, form())).rejects.toThrow("bug");
  });
});

describe("cancelGenerationAction", () => {
  it("cancels the job and returns to the goal with a notice", async () => {
    api.cancelJob.mockResolvedValue({});

    await expect(cancelGenerationAction(GOAL_ID, JOB_ID)).rejects.toThrow(
      `REDIRECT:${GOAL_PAGE}?notice=generation-cancelled`,
    );

    expect(api.cancelJob).toHaveBeenCalledWith("access-token-123", JOB_ID);
  });

  it("refuses ids that are not ids", async () => {
    await expect(cancelGenerationAction(GOAL_ID, "1/../2")).rejects.toThrow("NOT_FOUND");
    await expect(cancelGenerationAction("nope", JOB_ID)).rejects.toThrow("NOT_FOUND");

    expect(api.cancelJob).not.toHaveBeenCalled();
  });

  it("answers 404 for someone else's job", async () => {
    api.cancelJob.mockRejectedValue(new ApiError(404, "JOB_NOT_FOUND", "no"));

    await expect(cancelGenerationAction(GOAL_ID, JOB_ID)).rejects.toThrow("NOT_FOUND");
  });
});

describe("retryGenerationAction", () => {
  it("queues a new attempt and returns to the goal", async () => {
    api.retryJob.mockResolvedValue({ id: "new" });

    await expect(retryGenerationAction(GOAL_ID, JOB_ID)).rejects.toThrow(`REDIRECT:${GOAL_PAGE}`);

    expect(api.retryJob).toHaveBeenCalledWith("access-token-123", JOB_ID);
  });

  it("explains a refusal", async () => {
    api.retryJob.mockRejectedValue(new ApiError(409, "ROADMAP_JOB_ACTIVE", "x"));

    await expect(retryGenerationAction(GOAL_ID, JOB_ID)).rejects.toThrow(
      `REDIRECT:${GOAL_PAGE}?notice=already-generating`,
    );
  });
});

describe("makeRoadmapCurrentAction", () => {
  it("switches versions and lands on the roadmap with a notice", async () => {
    api.makeRoadmapCurrent.mockResolvedValue({});

    await expect(makeRoadmapCurrentAction(GOAL_ID, ROADMAP_ID)).rejects.toThrow(
      `REDIRECT:${GOAL_PAGE}/roadmap?notice=version-switched`,
    );

    expect(api.makeRoadmapCurrent).toHaveBeenCalledWith("access-token-123", ROADMAP_ID);
  });

  it("explains that an archived goal is read-only", async () => {
    api.makeRoadmapCurrent.mockRejectedValue(new ApiError(409, "GOAL_ARCHIVED", "x"));

    await expect(makeRoadmapCurrentAction(GOAL_ID, ROADMAP_ID)).rejects.toThrow(
      `REDIRECT:${GOAL_PAGE}/roadmap?notice=goal-archived`,
    );
  });

  it("refuses ids that are not ids and answers 404 for someone else's roadmap", async () => {
    await expect(makeRoadmapCurrentAction(GOAL_ID, "x")).rejects.toThrow("NOT_FOUND");
    api.makeRoadmapCurrent.mockRejectedValue(new ApiError(404, "ROADMAP_NOT_FOUND", "x"));

    await expect(makeRoadmapCurrentAction(GOAL_ID, ROADMAP_ID)).rejects.toThrow("NOT_FOUND");
  });
});
