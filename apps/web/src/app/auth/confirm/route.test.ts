// @vitest-environment node
import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

const auth = vi.hoisted(() => ({ verifyOtp: vi.fn() }));
const supabase = vi.hoisted(() => ({ current: null as unknown }));

vi.mock("next/navigation", () => ({
  redirect: (url: string) => {
    throw new Error(`REDIRECT:${url}`);
  },
}));
vi.mock("@/lib/supabase/server", () => ({ createClient: async () => supabase.current }));

import { GET } from "@/app/auth/confirm/route";

const call = (query: string) => GET(new NextRequest(`http://localhost:3000/auth/confirm?${query}`));

beforeEach(() => {
  vi.clearAllMocks();
  supabase.current = { auth };
});

describe("GET /auth/confirm", () => {
  it("exchanges a valid link for a session and goes to the dashboard", async () => {
    auth.verifyOtp.mockResolvedValue({ error: null });

    await expect(call("token_hash=abc123&type=email")).rejects.toThrow("REDIRECT:/dashboard");
    expect(auth.verifyOtp).toHaveBeenCalledWith({ type: "email", token_hash: "abc123" });
  });

  it("honours a same-site next path", async () => {
    auth.verifyOtp.mockResolvedValue({ error: null });

    await expect(call("token_hash=abc&type=signup&next=/goals/new")).rejects.toThrow(
      "REDIRECT:/goals/new",
    );
  });

  it.each(["https://evil.example", "//evil.example", "/\\evil.example"])(
    "will not redirect off-site via next=%s (the sample in Supabase's docs would)",
    async (next) => {
      auth.verifyOtp.mockResolvedValue({ error: null });

      await expect(
        call(`token_hash=abc&type=email&next=${encodeURIComponent(next)}`),
      ).rejects.toThrow("REDIRECT:/dashboard");
    },
  );

  it("reports a failed exchange (expired or reused link) on the sign-in page", async () => {
    auth.verifyOtp.mockResolvedValue({ error: { code: "otp_expired" } });

    await expect(call("token_hash=abc&type=email")).rejects.toThrow(
      "REDIRECT:/sign-in?error=confirmation_failed",
    );
  });

  it.each([
    ["no parameters", ""],
    ["no token", "type=email"],
    ["no type", "token_hash=abc"],
  ])("refuses a request with %s without contacting Supabase", async (_label, query) => {
    await expect(call(query)).rejects.toThrow("REDIRECT:/sign-in?error=confirmation_failed");
    expect(auth.verifyOtp).not.toHaveBeenCalled();
  });

  it.each(["recovery", "invite", "magiclink", "email_change", "nonsense"])(
    "refuses the link type %s, which this app never sends",
    async (type) => {
      await expect(call(`token_hash=abc&type=${type}`)).rejects.toThrow(
        "REDIRECT:/sign-in?error=confirmation_failed",
      );
      expect(auth.verifyOtp).not.toHaveBeenCalled();
    },
  );

  it("fails safely when Supabase is not configured", async () => {
    supabase.current = null;

    await expect(call("token_hash=abc&type=email")).rejects.toThrow(
      "REDIRECT:/sign-in?error=confirmation_failed",
    );
  });
});
