// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest";

const session = vi.hoisted(() => ({
  getSessionUser: vi.fn(),
  getAccessToken: vi.fn(),
}));
const api = vi.hoisted(() => ({
  createDownloadLink: vi.fn(),
  downloadExportFile: vi.fn(),
}));
const SUPABASE = "https://abc.supabase.co";

vi.mock("next/server", () => ({ connection: async () => undefined }));
vi.mock("@/lib/auth/session", () => session);
vi.mock("@/lib/env", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/env")>()),
  getPublicEnv: () => ({ NEXT_PUBLIC_SUPABASE_URL: SUPABASE }),
}));
vi.mock("@/lib/api/server", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/server")>()),
  ...api,
}));

import { GET } from "@/app/(app)/goals/[id]/exports/[exportId]/download/route";
import { ApiError } from "@/lib/api/server";
import { sessionEndedUrlFor, signInUrlFor } from "@/lib/auth/paths";
import { exportDownloadPath, exportsPath } from "@/lib/exports/paths";
import { EXPORT, GOAL } from "@/test-support/exports";

const ORIGIN = "http://localhost:3000";
const SIGNED = `${SUPABASE}/storage/v1/object/sign/exports/u/e/notes_pdf.pdf?token=t&download=a.pdf`;

function call(goalId = GOAL, exportId = EXPORT): Promise<Response> {
  const request = new Request(`${ORIGIN}${exportDownloadPath(goalId, exportId)}`);
  return GET(request, { params: Promise.resolve({ id: goalId, exportId }) });
}

const link = (url: string | null) => ({
  url,
  expires_at: url ? "2026-10-11T10:07:00Z" : null,
  file_name: "ownership-in-rust-notes.pdf",
});

beforeEach(() => {
  vi.clearAllMocks();
  session.getSessionUser.mockResolvedValue({
    id: "11111111-1111-4111-8111-111111111111",
    email: "a@b.c",
  });
  session.getAccessToken.mockResolvedValue("access-token-123");
});

describe("GET /goals/[id]/exports/[exportId]/download", () => {
  it("redirects to the short-lived signed link the API made for the caller, uncached", async () => {
    api.createDownloadLink.mockResolvedValue(link(SIGNED));

    const response = await call();

    expect(response.status).toBe(303);
    expect(response.headers.get("location")).toBe(SIGNED);
    expect(response.headers.get("cache-control")).toBe("private, no-store");
    expect(api.createDownloadLink).toHaveBeenCalledWith("access-token-123", EXPORT);
    expect(api.downloadExportFile).not.toHaveBeenCalled();
  });

  it.each([
    ["another site", "https://evil.example/storage/v1/object/sign/exports/x.pdf"],
    ["another bucket", `${SUPABASE}/storage/v1/object/sign/documents/u/d/x.pdf?token=t`],
  ])("refuses to redirect to %s", async (_name, url) => {
    api.createDownloadLink.mockResolvedValue(link(url));

    const response = await call();

    expect(response.status).toBe(502);
    expect(response.headers.get("location")).toBeNull();
  });

  it("passes the file on as an attachment when the server keeps files itself", async () => {
    api.createDownloadLink.mockResolvedValue(link(null));
    api.downloadExportFile.mockResolvedValue(
      new Response("%PDF-1.7", {
        headers: {
          "content-type": "application/pdf",
          "content-disposition": 'attachment; filename="ownership-in-rust-notes.pdf"',
        },
      }),
    );

    const response = await call();

    expect(response.status).toBe(200);
    expect(await response.text()).toBe("%PDF-1.7");
    expect(response.headers.get("content-disposition")).toBe(
      'attachment; filename="ownership-in-rust-notes.pdf"',
    );
    // Never sniffed or shown inline, whatever the API said the type was.
    expect(response.headers.get("content-type")).toBe("application/octet-stream");
    expect(response.headers.get("x-content-type-options")).toBe("nosniff");
    expect(response.headers.get("cache-control")).toBe("private, no-store");
  });

  it("still makes it an attachment when the API names no file", async () => {
    api.createDownloadLink.mockResolvedValue(link(null));
    api.downloadExportFile.mockResolvedValue(new Response("bytes"));

    const response = await call();

    expect(response.headers.get("content-disposition")).toBe("attachment");
  });

  it.each([
    ["goal", "not-a-uuid", EXPORT],
    ["export", GOAL, "..%2F..%2Fv1%2Fme"],
  ])("answers 404 for a malformed %s id without asking the API", async (_name, goalId, id) => {
    const response = await call(goalId, id);

    expect(response.status).toBe(404);
    expect(api.createDownloadLink).not.toHaveBeenCalled();
  });

  it("sends someone without a session to sign in, coming back to the download", async () => {
    session.getSessionUser.mockResolvedValue(null);

    const response = await call();

    expect(response.status).toBe(303);
    expect(response.headers.get("location")).toBe(
      `${ORIGIN}${signInUrlFor(exportDownloadPath(GOAL, EXPORT))}`,
    );
    expect(api.createDownloadLink).not.toHaveBeenCalled();
  });

  it("sends a session the API rejected to sign in again", async () => {
    api.createDownloadLink.mockRejectedValue(new ApiError(401, "UNAUTHENTICATED", "x"));

    const response = await call();

    expect(response.headers.get("location")).toBe(
      `${ORIGIN}${sessionEndedUrlFor(exportDownloadPath(GOAL, EXPORT))}`,
    );
  });

  it("answers 404 for another learner's export", async () => {
    api.createDownloadLink.mockRejectedValue(new ApiError(404, "NOT_FOUND", "Not found"));

    expect((await call()).status).toBe(404);
  });

  it("goes back to the exported files when the file is not made yet", async () => {
    api.createDownloadLink.mockRejectedValue(new ApiError(409, "EXPORT_NOT_READY", "Not ready"));

    const response = await call();

    expect(response.status).toBe(303);
    expect(response.headers.get("location")).toBe(
      `${ORIGIN}${exportsPath(GOAL)}?notice=export-not-ready`,
    );
  });

  it("answers with a plain message, not the API's, when storage fails", async () => {
    api.createDownloadLink.mockRejectedValue(
      new ApiError(503, "STORAGE_UNAVAILABLE", "upstream said something internal"),
    );

    const response = await call();

    expect(response.status).toBe(502);
    expect(await response.text()).toBe("The file can't be downloaded right now. Please try again.");
  });

  it("lets an unexpected error through", async () => {
    api.createDownloadLink.mockRejectedValue(new TypeError("boom"));

    await expect(call()).rejects.toThrow("boom");
  });
});
