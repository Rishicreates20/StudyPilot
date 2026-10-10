// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";

import { hardenAuthCookie, shouldUseSecureCookies } from "@/lib/supabase/cookies";

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("hardenAuthCookie", () => {
  it("makes the cookie unreadable by page scripts, whatever the library asked for", () => {
    const result = hardenAuthCookie({ path: "/", httpOnly: false, maxAge: 100 }, { secure: false });

    expect(result.httpOnly).toBe(true);
  });

  it("keeps the library's path and lifetime, including a deletion's maxAge of 0", () => {
    const result = hardenAuthCookie({ path: "/", maxAge: 0 }, { secure: false });

    expect(result).toMatchObject({ path: "/", maxAge: 0 });
  });

  it("does not let the cookie travel on cross-site requests", () => {
    const result = hardenAuthCookie({ sameSite: "none" }, { secure: true });

    expect(result.sameSite).toBe("lax");
  });

  it("applies the requested Secure flag", () => {
    expect(hardenAuthCookie({}, { secure: true }).secure).toBe(true);
    expect(hardenAuthCookie({}, { secure: false }).secure).toBe(false);
  });

  it("copes with no options at all", () => {
    expect(hardenAuthCookie(undefined, { secure: false })).toEqual({
      httpOnly: true,
      sameSite: "lax",
      secure: false,
    });
  });
});

describe("shouldUseSecureCookies", () => {
  it("is on for a production build using an https Supabase project", () => {
    vi.stubEnv("NODE_ENV", "production");

    expect(shouldUseSecureCookies("https://abcd.supabase.co")).toBe(true);
  });

  it("is off in development", () => {
    vi.stubEnv("NODE_ENV", "development");

    expect(shouldUseSecureCookies("https://abcd.supabase.co")).toBe(false);
  });

  it("is off when auth is served over plain http (the local stack)", () => {
    vi.stubEnv("NODE_ENV", "production");

    expect(shouldUseSecureCookies("http://127.0.0.1:54321")).toBe(false);
  });
});
