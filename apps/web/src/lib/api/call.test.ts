// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest";

const session = vi.hoisted(() => ({ requireApiSession: vi.fn() }));

vi.mock("next/navigation", () => ({
  redirect: (url: string) => {
    throw new Error(`REDIRECT:${url}`);
  },
  notFound: () => {
    throw new Error("NOT_FOUND");
  },
}));
vi.mock("@/lib/auth/session", () => session);

import { callApi } from "@/lib/api/call";
import { ApiError } from "@/lib/api/server";

beforeEach(() => {
  vi.clearAllMocks();
  session.requireApiSession.mockResolvedValue({ user: { id: "u1" }, accessToken: "token-abc" });
});

describe("callApi", () => {
  it("runs the call with the signed-in user's token and returns its result", async () => {
    const run = vi.fn().mockResolvedValue({ ok: true });

    await expect(callApi("/goals/x", run)).resolves.toEqual({ ok: true });
    expect(run).toHaveBeenCalledWith("token-abc");
    expect(session.requireApiSession).toHaveBeenCalledWith("/goals/x");
  });

  it("does not run the call at all when there is no session", async () => {
    session.requireApiSession.mockImplementation(() => {
      throw new Error("REDIRECT:/sign-in");
    });
    const run = vi.fn();

    await expect(callApi("/goals/x", run)).rejects.toThrow("REDIRECT:/sign-in");
    expect(run).not.toHaveBeenCalled();
  });

  it("sends the user to sign in again, without looping, when the API refuses the session", async () => {
    const run = vi.fn().mockRejectedValue(new ApiError(401, "ACCOUNT_NOT_FOUND", "gone"));

    await expect(callApi("/goals/x", run)).rejects.toThrow(
      "REDIRECT:/sign-in?next=%2Fgoals%2Fx&error=session_ended",
    );
  });

  it("shows the not-found page when the API says 404 (missing and foreign look the same)", async () => {
    const run = vi.fn().mockRejectedValue(new ApiError(404, "GOAL_NOT_FOUND", "Goal not found."));

    await expect(callApi("/goals/x", run)).rejects.toThrow("NOT_FOUND");
  });

  it.each([
    new ApiError(503, "SERVICE_UNAVAILABLE", "down"),
    new ApiError(422, "INVALID_CURSOR", "bad cursor"),
    new ApiError(0, "API_UNREACHABLE", "unreachable"),
    new TypeError("bug"),
  ])("hands any other failure back to the page (%#)", async (error) => {
    const run = vi.fn().mockRejectedValue(error);

    await expect(callApi("/goals/x", run)).rejects.toBe(error);
  });
});
