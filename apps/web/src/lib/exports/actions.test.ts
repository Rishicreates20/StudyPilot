// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest";

const session = vi.hoisted(() => ({
  getSessionUser: vi.fn(),
  getAccessToken: vi.fn(),
}));
const api = vi.hoisted(() => ({
  requestLessonExport: vi.fn(),
  requestRoadmapExport: vi.fn(),
  deleteExport: vi.fn(),
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
import { sessionEndedUrlFor, signInUrlFor } from "@/lib/auth/paths";
import {
  deleteExportAction,
  requestLessonExportAction,
  requestRoadmapExportAction,
} from "@/lib/exports/actions";
import { exportsPath } from "@/lib/exports/paths";
import { EXPORT, GOAL, LESSON, ROADMAP, exportItem } from "@/test-support/exports";

const LIST = exportsPath(GOAL);
const STUDY = `/goals/${GOAL}/learn/22222222-2222-4222-8222-222222222222`;
const ROADMAP_PAGE = `/goals/${GOAL}/roadmap`;

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

describe("requestLessonExportAction", () => {
  it("asks for the clicked format with the caller's token, then shows the exported files", async () => {
    api.requestLessonExport.mockResolvedValue(exportItem({ status: "processing" }));

    await expect(
      requestLessonExportAction(GOAL, LESSON, STUDY, form({ format: "revision_pdf" })),
    ).rejects.toThrow(`REDIRECT:${LIST}?notice=export-requested`);

    expect(api.requestLessonExport).toHaveBeenCalledWith(
      "access-token-123",
      LESSON,
      "revision_pdf",
    );
  });

  it("says so when the file was already made", async () => {
    api.requestLessonExport.mockResolvedValue(exportItem({ status: "ready" }));

    await expect(
      requestLessonExportAction(GOAL, LESSON, STUDY, form({ format: "notes_pdf" })),
    ).rejects.toThrow(`REDIRECT:${LIST}?notice=export-ready`);
  });

  it.each([
    ["no format", {}],
    ["an unknown format", { format: "docx" }],
    ["a roadmap-only format", { format: "roadmap_pdf" }],
  ])("refuses %s without calling the API", async (_name, fields) => {
    await expect(requestLessonExportAction(GOAL, LESSON, STUDY, form(fields))).rejects.toThrow(
      "NOT_FOUND",
    );
    expect(api.requestLessonExport).not.toHaveBeenCalled();
  });

  it.each([
    ["goal", "not-a-uuid", LESSON],
    ["lesson", GOAL, "../../v1/me"],
  ])("refuses a malformed %s id without calling the API", async (_name, goalId, lessonId) => {
    await expect(
      requestLessonExportAction(goalId, lessonId, STUDY, form({ format: "notes_pdf" })),
    ).rejects.toThrow("NOT_FOUND");
    expect(api.requestLessonExport).not.toHaveBeenCalled();
  });

  it("sends someone without a session to sign in, coming back to the page", async () => {
    session.getSessionUser.mockResolvedValue(null);

    await expect(
      requestLessonExportAction(GOAL, LESSON, STUDY, form({ format: "notes_pdf" })),
    ).rejects.toThrow(`REDIRECT:${signInUrlFor(STUDY)}`);
    expect(api.requestLessonExport).not.toHaveBeenCalled();
  });

  it("goes back to the page with a notice when the API refuses", async () => {
    api.requestLessonExport.mockRejectedValue(
      new ApiError(429, "EXPORT_ALLOWANCE_USED", "Daily limit"),
    );

    await expect(
      requestLessonExportAction(GOAL, LESSON, STUDY, form({ format: "notes_pdf" })),
    ).rejects.toThrow(`REDIRECT:${STUDY}?notice=export-limit-today`);
  });

  it("treats another learner's lesson as not found", async () => {
    api.requestLessonExport.mockRejectedValue(new ApiError(404, "NOT_FOUND", "Not found"));

    await expect(
      requestLessonExportAction(GOAL, LESSON, STUDY, form({ format: "notes_pdf" })),
    ).rejects.toThrow("NOT_FOUND");
  });

  it("sends a session the API rejected to sign in again", async () => {
    api.requestLessonExport.mockRejectedValue(new ApiError(401, "UNAUTHENTICATED", "x"));

    await expect(
      requestLessonExportAction(GOAL, LESSON, STUDY, form({ format: "notes_pdf" })),
    ).rejects.toThrow(`REDIRECT:${sessionEndedUrlFor(STUDY)}`);
  });

  it("lets an unexpected error through to the error boundary", async () => {
    api.requestLessonExport.mockRejectedValue(new TypeError("boom"));

    await expect(
      requestLessonExportAction(GOAL, LESSON, STUDY, form({ format: "notes_pdf" })),
    ).rejects.toThrow("boom");
  });

  it.each([
    ["another site", "https://evil.example/goals"],
    ["a protocol-relative link", "//evil.example"],
    ["another goal", "/goals/22222222-2222-4222-8222-222222222222/roadmap"],
    ["a page outside goals", "/settings"],
    ["a climb out of the goal", `/goals/${GOAL}/../../settings`],
    ["an encoded climb out of the goal", `/goals/${GOAL}/%2e%2e/%2e%2e/settings`],
    ["a mixed-case encoded climb", `/goals/${GOAL}/learn/%2E%2e/%2e%2E/settings`],
    ["a half-encoded climb", `/goals/${GOAL}/.%2e/.%2E/settings`],
    ["an encoded slash", `/goals/${GOAL}%2F..%2F..%2Fsettings`],
    ["a page with its own query", `/goals/${GOAL}/roadmap?notice=export-deleted`],
    ["a page with a fragment", `/goals/${GOAL}/roadmap#top`],
  ])("never comes back to %s, only to the goal page", async (_name, returnTo) => {
    api.requestLessonExport.mockRejectedValue(new ApiError(409, "EXPORT_BUSY", "Busy"));

    await expect(
      requestLessonExportAction(GOAL, LESSON, returnTo, form({ format: "notes_pdf" })),
    ).rejects.toThrow(`REDIRECT:/goals/${GOAL}?notice=export-busy`);
  });

  it("comes back to the page as a browser would resolve it, when it stays in the goal", async () => {
    api.requestLessonExport.mockRejectedValue(new ApiError(409, "EXPORT_BUSY", "Busy"));

    await expect(
      requestLessonExportAction(
        GOAL,
        LESSON,
        `/goals/${GOAL}/learn/x/%2e%2e/./roadmap`,
        form({ format: "notes_pdf" }),
      ),
    ).rejects.toThrow(`REDIRECT:/goals/${GOAL}/learn/roadmap?notice=export-busy`);
  });
});

describe("requestRoadmapExportAction", () => {
  it("asks for a roadmap format with the caller's token", async () => {
    api.requestRoadmapExport.mockResolvedValue(
      exportItem({ lesson_id: null, roadmap_id: ROADMAP, format: "roadmap_pdf" }),
    );

    await expect(
      requestRoadmapExportAction(GOAL, ROADMAP, ROADMAP_PAGE, form({ format: "roadmap_pdf" })),
    ).rejects.toThrow(`REDIRECT:${LIST}?notice=export-ready`);

    expect(api.requestRoadmapExport).toHaveBeenCalledWith(
      "access-token-123",
      ROADMAP,
      "roadmap_pdf",
    );
  });

  it.each(["notes_pdf", "revision_pdf", "docx"])(
    "refuses %s for a roadmap without calling the API",
    async (format) => {
      await expect(
        requestRoadmapExportAction(GOAL, ROADMAP, ROADMAP_PAGE, form({ format })),
      ).rejects.toThrow("NOT_FOUND");
      expect(api.requestRoadmapExport).not.toHaveBeenCalled();
    },
  );

  it("goes back to the roadmap with a notice when the goal is archived", async () => {
    api.requestRoadmapExport.mockRejectedValue(new ApiError(409, "GOAL_ARCHIVED", "Archived"));

    await expect(
      requestRoadmapExportAction(GOAL, ROADMAP, ROADMAP_PAGE, form({ format: "slides_pptx" })),
    ).rejects.toThrow(`REDIRECT:${ROADMAP_PAGE}?notice=export-goal-archived`);
  });
});

describe("deleteExportAction", () => {
  it("deletes with the caller's token and says so on the exported files", async () => {
    api.deleteExport.mockResolvedValue(undefined);

    await expect(deleteExportAction(GOAL, EXPORT)).rejects.toThrow(
      `REDIRECT:${LIST}?notice=export-deleted`,
    );
    expect(api.deleteExport).toHaveBeenCalledWith("access-token-123", EXPORT);
  });

  it("refuses a malformed id without calling the API", async () => {
    await expect(deleteExportAction(GOAL, "x")).rejects.toThrow("NOT_FOUND");
    expect(api.deleteExport).not.toHaveBeenCalled();
  });

  it("explains a storage failure", async () => {
    api.deleteExport.mockRejectedValue(new ApiError(503, "STORAGE_UNAVAILABLE", "Down"));

    await expect(deleteExportAction(GOAL, EXPORT)).rejects.toThrow(
      `REDIRECT:${LIST}?notice=storage-unavailable`,
    );
  });

  it("treats another learner's export as not found", async () => {
    api.deleteExport.mockRejectedValue(new ApiError(404, "NOT_FOUND", "Not found"));

    await expect(deleteExportAction(GOAL, EXPORT)).rejects.toThrow("NOT_FOUND");
  });

  it("sends a session the API rejected to sign in again", async () => {
    api.deleteExport.mockRejectedValue(new ApiError(401, "UNAUTHENTICATED", "x"));

    await expect(deleteExportAction(GOAL, EXPORT)).rejects.toThrow(
      `REDIRECT:${sessionEndedUrlFor(LIST)}`,
    );
  });
});
