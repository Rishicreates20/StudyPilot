// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest";

const session = vi.hoisted(() => ({
  getSessionUser: vi.fn(),
  getAccessToken: vi.fn(),
}));
const api = vi.hoisted(() => ({
  startVideoSearch: vi.fn(),
  cancelJob: vi.fn(),
  retryJob: vi.fn(),
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
  cancelVideoSearchAction,
  findVideosAction,
  retryVideoSearchAction,
} from "@/lib/videos/actions";
import { GOAL, ITEM, JOB } from "@/test-support/lessons";

const STUDY = `/goals/${GOAL}/learn/${ITEM}`;

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

describe("findVideosAction", () => {
  it("starts a first search with the caller's token and returns to the videos card", async () => {
    api.startVideoSearch.mockResolvedValue({ id: JOB });

    await expect(findVideosAction(GOAL, ITEM, form())).rejects.toThrow(`REDIRECT:${STUDY}#videos`);

    expect(api.startVideoSearch).toHaveBeenCalledWith("access-token-123", ITEM, false);
  });

  it("searches again only when the form says so", async () => {
    api.startVideoSearch.mockResolvedValue({ id: JOB });

    await expect(findVideosAction(GOAL, ITEM, form({ refresh: "1" }))).rejects.toThrow("REDIRECT");
    await expect(findVideosAction(GOAL, ITEM, form({ refresh: "yes" }))).rejects.toThrow(
      "REDIRECT",
    );

    expect(api.startVideoSearch.mock.calls.map((call) => call[2])).toEqual([true, false]);
  });

  it.each([
    ["VIDEOS_EXIST", 409, "videos-exist"],
    ["VIDEO_SEARCH_LIMIT_REACHED", 429, "videos-limit"],
    ["VIDEOS_NOT_CONFIGURED", 503, "videos-unavailable"],
    ["GOAL_ARCHIVED", 409, "goal-archived"],
    ["ROADMAP_NOT_CURRENT", 409, "roadmap-not-current"],
    ["SOMETHING_ELSE", 409, "status-conflict"],
    ["API_UNREACHABLE", 0, "unavailable"],
  ])("explains a refusal with %s through a notice", async (code, status, notice) => {
    api.startVideoSearch.mockRejectedValue(new ApiError(status, code, "refused"));

    await expect(findVideosAction(GOAL, ITEM, form())).rejects.toThrow(
      `REDIRECT:${STUDY}?notice=${notice}`,
    );
  });

  it("stays quiet when a search is already running", async () => {
    api.startVideoSearch.mockRejectedValue(new ApiError(409, "VIDEO_SEARCH_ACTIVE", "busy"));

    await expect(findVideosAction(GOAL, ITEM, form())).rejects.toThrow(`REDIRECT:${STUDY}#videos`);
  });

  it("sends a missing or someone else's topic to the not-found page", async () => {
    api.startVideoSearch.mockRejectedValue(new ApiError(404, "TOPIC_NOT_FOUND", "no"));

    await expect(findVideosAction(GOAL, ITEM, form())).rejects.toThrow("NOT_FOUND");
  });

  it("sends an ended session to sign-in with the marker that shows the form", async () => {
    api.startVideoSearch.mockRejectedValue(new ApiError(401, "UNAUTHENTICATED", "no"));

    await expect(findVideosAction(GOAL, ITEM, form())).rejects.toThrow(
      /REDIRECT:\/sign-in\?.*ended/,
    );
  });

  it.each(["../me", "123", "", GOAL + "x"])(
    "refuses the identifier %j before it can reach an API path",
    async (bad) => {
      await expect(findVideosAction(bad, ITEM, form())).rejects.toThrow("NOT_FOUND");
      await expect(findVideosAction(GOAL, bad, form())).rejects.toThrow("NOT_FOUND");
      expect(api.startVideoSearch).not.toHaveBeenCalled();
    },
  );
});

describe("cancelVideoSearchAction and retryVideoSearchAction", () => {
  it("cancels the job named by the page", async () => {
    api.cancelJob.mockResolvedValue({ id: JOB });

    await expect(cancelVideoSearchAction(GOAL, ITEM, JOB)).rejects.toThrow(
      `REDIRECT:${STUDY}#videos`,
    );
    expect(api.cancelJob).toHaveBeenCalledWith("access-token-123", JOB);
  });

  it("retries a failed search", async () => {
    api.retryJob.mockResolvedValue({ id: JOB });

    await expect(retryVideoSearchAction(GOAL, ITEM, JOB)).rejects.toThrow(
      `REDIRECT:${STUDY}#videos`,
    );
    expect(api.retryJob).toHaveBeenCalledWith("access-token-123", JOB);
  });

  it("refuses a made-up job id", async () => {
    await expect(retryVideoSearchAction(GOAL, ITEM, "not-a-job")).rejects.toThrow("NOT_FOUND");
    await expect(cancelVideoSearchAction(GOAL, ITEM, "../x")).rejects.toThrow("NOT_FOUND");
    expect(api.retryJob).not.toHaveBeenCalled();
    expect(api.cancelJob).not.toHaveBeenCalled();
  });
});
