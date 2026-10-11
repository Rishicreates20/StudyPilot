// @vitest-environment node
import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

const auth = vi.hoisted(() => ({ verifyOtp: vi.fn(), exchangeCodeForSession: vi.fn() }));
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

describe("GET /auth/confirm with a code (Supabase's built-in confirmation email)", () => {
  const CODE = "c095dca5-53b7-4574-925a-243491f08a72";

  it("turns the code into a session and goes where the link asked", async () => {
    auth.exchangeCodeForSession.mockResolvedValue({ error: null });

    await expect(call(`code=${CODE}&next=/onboarding`)).rejects.toThrow("REDIRECT:/onboarding");
    expect(auth.exchangeCodeForSession).toHaveBeenCalledWith(CODE);
    expect(auth.verifyOtp).not.toHaveBeenCalled();
  });

  it("goes to the dashboard when no destination was given", async () => {
    auth.exchangeCodeForSession.mockResolvedValue({ error: null });

    await expect(call(`code=${CODE}`)).rejects.toThrow("REDIRECT:/dashboard");
  });

  it.each(["https://evil.example", "//evil.example", "/\\evil.example"])(
    "will not redirect off-site via next=%s",
    async (next) => {
      auth.exchangeCodeForSession.mockResolvedValue({ error: null });

      await expect(call(`code=${CODE}&next=${encodeURIComponent(next)}`)).rejects.toThrow(
        "REDIRECT:/dashboard",
      );
    },
  );

  it("explains kindly when the code cannot be used (usually another browser or device)", async () => {
    auth.exchangeCodeForSession.mockResolvedValue({ error: { code: "flow_state_not_found" } });

    await expect(call(`code=${CODE}`)).rejects.toThrow("REDIRECT:/sign-in?error=confirm_signin");
  });

  it("does the same when Supabase is not configured", async () => {
    supabase.current = null;

    await expect(call(`code=${CODE}`)).rejects.toThrow("REDIRECT:/sign-in?error=confirm_signin");
  });

  it.each(["", "short", "has space in it", "<script>alert(1)</script>", "x".repeat(200)])(
    "never sends the odd code %j to Supabase",
    async (code) => {
      await expect(call(`code=${encodeURIComponent(code)}`)).rejects.toThrow(
        "REDIRECT:/sign-in?error=confirmation_failed",
      );
      expect(auth.exchangeCodeForSession).not.toHaveBeenCalled();
    },
  );

  it("prefers nothing over guessing: a link with both kinds of parameter uses the code only", async () => {
    auth.exchangeCodeForSession.mockResolvedValue({ error: null });

    await expect(call(`code=${CODE}&token_hash=abc&type=email`)).rejects.toThrow("REDIRECT");

    expect(auth.exchangeCodeForSession).toHaveBeenCalledTimes(1);
    expect(auth.verifyOtp).not.toHaveBeenCalled();
  });
});
