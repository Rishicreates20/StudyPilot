// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest";

const session = vi.hoisted(() => ({
  getSessionUser: vi.fn(),
  getAccessToken: vi.fn(),
}));
const api = vi.hoisted(() => ({
  uploadDocument: vi.fn(),
  pasteDocument: vi.fn(),
  renameDocument: vi.fn(),
  editDocumentPage: vi.fn(),
  confirmDocument: vi.fn(),
  reprocessDocument: vi.fn(),
  deleteDocument: vi.fn(),
  searchDocuments: vi.fn(),
  cancelJob: vi.fn(),
}));
const cache = vi.hoisted(() => ({ revalidatePath: vi.fn() }));

vi.mock("next/navigation", () => ({
  redirect: (url: string) => {
    throw new Error(`REDIRECT:${url}`);
  },
  notFound: () => {
    throw new Error("NOT_FOUND");
  },
}));
vi.mock("next/cache", () => cache);
vi.mock("@/lib/auth/session", () => session);
vi.mock("@/lib/api/server", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/server")>()),
  ...api,
}));

import { ApiError } from "@/lib/api/server";
import { sessionEndedUrlFor, signInUrlFor } from "@/lib/auth/paths";
import {
  cancelDocumentJobAction,
  confirmDocumentAction,
  deleteDocumentAction,
  pasteDocumentAction,
  reprocessDocumentAction,
  renameDocumentAction,
  savePageAction,
  searchDocumentsAction,
  uploadDocumentAction,
} from "@/lib/documents/actions";
import { documentPath, documentsPath } from "@/lib/documents/paths";
import { DOC, DOC_JOB, GOAL, studyDocument } from "@/test-support/documents";

const LIST = documentsPath(GOAL);
const PAGE = documentPath(GOAL, DOC);
const IDLE = { status: "idle" } as const;

function form(fields: Record<string, string | File> = {}): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(fields)) data.append(key, value);
  return data;
}

const notes = () => new File(["Ownership means one owner."], "notes.txt", { type: "text/plain" });

beforeEach(() => {
  vi.clearAllMocks();
  session.getSessionUser.mockResolvedValue({
    id: "11111111-1111-4111-8111-111111111111",
    email: "a@b.c",
  });
  session.getAccessToken.mockResolvedValue("access-token-123");
});

describe("uploadDocumentAction", () => {
  it("sends the file and an optional title with the caller's token, then shows the document", async () => {
    api.uploadDocument.mockResolvedValue(studyDocument());
    const file = notes();

    await expect(
      uploadDocumentAction(GOAL, IDLE, form({ file, title: "  Chapter 1  " })),
    ).rejects.toThrow(`REDIRECT:${PAGE}`);

    expect(api.uploadDocument).toHaveBeenCalledWith("access-token-123", GOAL, file, "Chapter 1");
  });

  it("does not need a title", async () => {
    api.uploadDocument.mockResolvedValue(studyDocument());

    await expect(uploadDocumentAction(GOAL, IDLE, form({ file: notes() }))).rejects.toThrow(
      `REDIRECT:${PAGE}`,
    );

    expect(api.uploadDocument.mock.calls[0]?.[3]).toBeNull();
  });

  it("asks for a file when none (or an empty one) was chosen, without calling the API", async () => {
    const none = await uploadDocumentAction(GOAL, IDLE, form({ title: "x" }));
    const empty = await uploadDocumentAction(GOAL, IDLE, form({ file: new File([], "empty.txt") }));

    for (const result of [none, empty]) {
      expect(result).toMatchObject({
        status: "error",
        fieldErrors: { file: "Choose a file to upload." },
      });
    }
    expect(api.uploadDocument).not.toHaveBeenCalled();
  });

  it("keeps what the learner typed when the title is too long", async () => {
    const long = "x".repeat(201);

    const result = await uploadDocumentAction(GOAL, IDLE, form({ file: notes(), title: long }));

    expect(result).toMatchObject({
      status: "error",
      fieldErrors: { title: "Use 200 characters or fewer." },
      values: { title: long },
    });
    expect(api.uploadDocument).not.toHaveBeenCalled();
  });

  it.each([
    [413, "FILE_TOO_LARGE", "That file is larger than the 10 MB limit."],
    [415, "FILE_TYPE_UNSUPPORTED", "This kind of file can't be used."],
    [422, "FILE_EMPTY", "That file is empty."],
    [409, "DOCUMENT_EXISTS", "You already added this file to this goal."],
  ])(
    "shows the API's explanation next to the file input for a %s",
    async (status, code, message) => {
      api.uploadDocument.mockRejectedValue(new ApiError(status, code, message));

      const result = await uploadDocumentAction(GOAL, IDLE, form({ file: notes() }));

      expect(result).toMatchObject({ status: "error", fieldErrors: { file: message } });
    },
  );

  it("says plainly that nothing was saved when the service is down", async () => {
    api.uploadDocument.mockRejectedValue(new ApiError(0, "API_UNREACHABLE", "unreachable"));

    const result = await uploadDocumentAction(GOAL, IDLE, form({ file: notes() }));

    expect(result).toMatchObject({ status: "error" });
    expect(result.status === "error" ? result.formError : "").toMatch(/nothing was saved/i);
  });

  it("goes to sign-in when there is no session, and again when the API refuses the token", async () => {
    session.getSessionUser.mockResolvedValue(null);
    await expect(uploadDocumentAction(GOAL, IDLE, form({ file: notes() }))).rejects.toThrow(
      `REDIRECT:${signInUrlFor(LIST)}`,
    );

    session.getSessionUser.mockResolvedValue({ id: "u", email: null });
    api.uploadDocument.mockRejectedValue(new ApiError(401, "TOKEN_EXPIRED", "expired"));
    await expect(uploadDocumentAction(GOAL, IDLE, form({ file: notes() }))).rejects.toThrow(
      `REDIRECT:${sessionEndedUrlFor(LIST)}`,
    );
  });

  it("shows the not-found page for someone else's goal and refuses a made-up id", async () => {
    api.uploadDocument.mockRejectedValue(new ApiError(404, "GOAL_NOT_FOUND", "no"));
    await expect(uploadDocumentAction(GOAL, IDLE, form({ file: notes() }))).rejects.toThrow(
      "NOT_FOUND",
    );

    await expect(uploadDocumentAction("../me", IDLE, form({ file: notes() }))).rejects.toThrow(
      "NOT_FOUND",
    );
  });
});

describe("pasteDocumentAction", () => {
  it("adds the text with the caller's token and shows the document", async () => {
    api.pasteDocument.mockResolvedValue(studyDocument({ kind: "pasted" }));

    await expect(
      pasteDocumentAction(GOAL, IDLE, form({ title: "My notes", text: "  Ownership.  " })),
    ).rejects.toThrow(`REDIRECT:${PAGE}`);

    expect(api.pasteDocument).toHaveBeenCalledWith("access-token-123", GOAL, {
      title: "My notes",
      text: "Ownership.",
    });
  });

  it("needs a title and some text, and keeps what was typed", async () => {
    const result = await pasteDocumentAction(GOAL, IDLE, form({ title: " ", text: "" }));

    expect(result).toMatchObject({
      status: "error",
      fieldErrors: { title: "Give this material a title.", text: "Paste some text." },
    });
    expect(api.pasteDocument).not.toHaveBeenCalled();
  });

  it("shows a too-large paste next to the text", async () => {
    api.pasteDocument.mockRejectedValue(new ApiError(413, "FILE_TOO_LARGE", "Too large."));

    const result = await pasteDocumentAction(GOAL, IDLE, form({ title: "t", text: "words" }));

    expect(result).toMatchObject({ status: "error", fieldErrors: { text: "Too large." } });
  });
});

describe("renameDocumentAction and savePageAction", () => {
  it("renames and refreshes the page", async () => {
    api.renameDocument.mockResolvedValue(studyDocument({ title: "Chapter 4" }));

    const result = await renameDocumentAction(GOAL, DOC, IDLE, form({ title: "Chapter 4" }));

    expect(api.renameDocument).toHaveBeenCalledWith("access-token-123", DOC, "Chapter 4");
    expect(cache.revalidatePath).toHaveBeenCalledWith(PAGE);
    expect(result).toMatchObject({ status: "success", values: { title: "Chapter 4" } });
  });

  it("will not rename to nothing", async () => {
    const result = await renameDocumentAction(GOAL, DOC, IDLE, form({ title: "  " }));

    expect(result).toMatchObject({ status: "error", fieldErrors: { title: expect.any(String) } });
    expect(api.renameDocument).not.toHaveBeenCalled();
  });

  it("saves a corrected page and keeps showing what was saved", async () => {
    api.editDocumentPage.mockResolvedValue({ page_number: 2, text: "Ownership means one owner." });

    const result = await savePageAction(
      GOAL,
      DOC,
      2,
      IDLE,
      form({ text: "Ownership means one owner." }),
    );

    expect(api.editDocumentPage).toHaveBeenCalledWith(
      "access-token-123",
      DOC,
      2,
      "Ownership means one owner.",
    );
    expect(cache.revalidatePath).toHaveBeenCalledWith(PAGE);
    expect(result).toMatchObject({
      status: "success",
      values: { text: "Ownership means one owner." },
    });
  });

  it("explains when the document is no longer waiting for review", async () => {
    api.editDocumentPage.mockRejectedValue(
      new ApiError(409, "DOCUMENT_NOT_IN_REVIEW", "Text can only be corrected while..."),
    );

    const result = await savePageAction(GOAL, DOC, 1, IDLE, form({ text: "x" }));

    expect(result).toMatchObject({ status: "error" });
    expect(result.status === "error" ? result.formError : "").toMatch(
      /no longer waiting for review/i,
    );
  });

  it("refuses a page number that cannot be one", async () => {
    await expect(savePageAction(GOAL, DOC, 0, IDLE, form({ text: "x" }))).rejects.toThrow(
      "NOT_FOUND",
    );
    await expect(savePageAction(GOAL, DOC, 1.5, IDLE, form({ text: "x" }))).rejects.toThrow(
      "NOT_FOUND",
    );
  });
});

describe("confirm, reprocess, cancel and delete", () => {
  it("confirms the text and goes back to the document to follow indexing", async () => {
    api.confirmDocument.mockResolvedValue(studyDocument());

    await expect(confirmDocumentAction(GOAL, DOC)).rejects.toThrow(`REDIRECT:${PAGE}`);

    expect(api.confirmDocument).toHaveBeenCalledWith("access-token-123", DOC);
  });

  it("processes the file again", async () => {
    api.reprocessDocument.mockResolvedValue(studyDocument());

    await expect(reprocessDocumentAction(GOAL, DOC)).rejects.toThrow(`REDIRECT:${PAGE}`);
  });

  it.each([
    ["DOCUMENT_BUSY", 409, "document-busy"],
    ["GOAL_ARCHIVED", 409, "goal-archived"],
    ["NOTHING_TO_CONFIRM", 409, "nothing-to-confirm"],
    ["DOCUMENT_LIMIT_REACHED_TODAY", 429, "document-limit-today"],
    ["STORAGE_NOT_CONFIGURED", 503, "storage-unavailable"],
    ["AI_NOT_CONFIGURED", 503, "documents-ai-unavailable"],
    ["SOMETHING_ELSE", 409, "status-conflict"],
    ["SOMETHING_ELSE", 500, "unavailable"],
  ])("explains a refusal (%s) with a fixed notice", async (code, status, notice) => {
    api.reprocessDocument.mockRejectedValue(new ApiError(status, code, "from the API"));

    await expect(reprocessDocumentAction(GOAL, DOC)).rejects.toThrow(
      `REDIRECT:${PAGE}?notice=${notice}`,
    );
  });

  it("stops a job and says so", async () => {
    api.cancelJob.mockResolvedValue({});

    await expect(cancelDocumentJobAction(GOAL, DOC, DOC_JOB)).rejects.toThrow(
      `REDIRECT:${PAGE}?notice=document-cancelled`,
    );

    expect(api.cancelJob).toHaveBeenCalledWith("access-token-123", DOC_JOB);
  });

  it("deletes and returns to the list with a notice", async () => {
    api.deleteDocument.mockResolvedValue(undefined);

    await expect(deleteDocumentAction(GOAL, DOC)).rejects.toThrow(
      `REDIRECT:${LIST}?notice=document-deleted`,
    );

    expect(api.deleteDocument).toHaveBeenCalledWith("access-token-123", DOC);
  });

  it("keeps the document and explains when it cannot be deleted", async () => {
    api.deleteDocument.mockRejectedValue(new ApiError(409, "DOCUMENT_BUSY", "busy"));

    await expect(deleteDocumentAction(GOAL, DOC)).rejects.toThrow(
      `REDIRECT:${PAGE}?notice=document-busy`,
    );
  });

  it("shows not-found for someone else's document and refuses made-up ids", async () => {
    api.deleteDocument.mockRejectedValue(new ApiError(404, "DOCUMENT_NOT_FOUND", "no"));
    await expect(deleteDocumentAction(GOAL, DOC)).rejects.toThrow("NOT_FOUND");

    for (const run of [
      () => deleteDocumentAction(GOAL, "../x"),
      () => confirmDocumentAction("x", DOC),
      () => reprocessDocumentAction(GOAL, "nope"),
      () => cancelDocumentJobAction(GOAL, DOC, "?"),
    ]) {
      await expect(run()).rejects.toThrow("NOT_FOUND");
    }
  });
});

describe("searchDocumentsAction", () => {
  it("returns the passages that were found", async () => {
    const result = { items: [], enough_evidence: false, searched_documents: 1 };
    api.searchDocuments.mockResolvedValue(result);

    const state = await searchDocumentsAction(GOAL, IDLE, form({ query: "  ownership  " }));

    expect(api.searchDocuments).toHaveBeenCalledWith("access-token-123", GOAL, {
      query: "ownership",
    });
    expect(state).toEqual({ status: "results", query: "ownership", result });
  });

  it("will not search for nothing", async () => {
    const state = await searchDocumentsAction(GOAL, IDLE, form({ query: "x" }));

    expect(state).toMatchObject({ status: "error", message: "Type a question or a few words." });
    expect(api.searchDocuments).not.toHaveBeenCalled();
  });

  it.each([
    [429, "SEARCH_RATE_LIMITED", /very quickly/i],
    [503, "AI_NOT_CONFIGURED", /isn't available right now/i],
    [0, "API_UNREACHABLE", /isn't available right now/i],
  ])("explains a failed search (%s) kindly", async (status, code, message) => {
    api.searchDocuments.mockRejectedValue(new ApiError(status, code, "x"));

    const state = await searchDocumentsAction(GOAL, IDLE, form({ query: "ownership" }));

    expect(state).toMatchObject({ status: "error", query: "ownership" });
    expect(state.status === "error" ? state.message : "").toMatch(message);
  });
});
