// @vitest-environment node
import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

const claims = vi.hoisted(() => ({ getClaims: vi.fn() }));
type CookieAdapter = {
  setAll: (
    cookies: { name: string; value: string; options: Record<string, unknown> }[],
    headers: Record<string, string>,
  ) => void;
};
const captured = vi.hoisted(() => ({ cookies: null as CookieAdapter | null }));
const config = vi.hoisted(() => ({
  value: { url: "https://abcd.supabase.co", publishableKey: "sb_publishable_abcdefghij" } as {
    url: string;
    publishableKey: string;
  } | null,
}));

vi.mock("@supabase/ssr", () => ({
  createServerClient: (_url: string, _key: string, options: { cookies: CookieAdapter }) => {
    captured.cookies = options.cookies;
    return { auth: { getClaims: claims.getClaims } };
  },
}));
vi.mock("@/lib/env", () => ({ getSupabaseConfig: () => config.value }));

import { updateSession } from "@/lib/supabase/proxy";

const request = (path: string) => new NextRequest(`http://localhost:3000${path}`);

beforeEach(() => {
  vi.clearAllMocks();
  config.value = { url: "https://abcd.supabase.co", publishableKey: "sb_publishable_abcdefghij" };
});

describe("updateSession", () => {
  it("sends a signed-out visitor from a protected page to sign in, remembering the page", async () => {
    claims.getClaims.mockResolvedValue({ data: null });

    const response = await updateSession(request("/dashboard?cursor=abc"));

    expect(response.status).toBe(307);
    const location = new URL(response.headers.get("location") ?? "");
    expect(location.pathname).toBe("/sign-in");
    expect(location.searchParams.get("next")).toBe("/dashboard?cursor=abc");
  });

  it("protects nested routes too", async () => {
    claims.getClaims.mockResolvedValue({ data: null });

    const response = await updateSession(request("/goals/new"));

    expect(response.status).toBe(307);
  });

  it("lets a signed-in visitor through", async () => {
    claims.getClaims.mockResolvedValue({ data: { claims: { sub: "u1" } } });

    const response = await updateSession(request("/dashboard"));

    expect(response.status).toBe(200);
    expect(response.headers.get("location")).toBeNull();
  });

  it.each(["/", "/sign-in", "/sign-up", "/status", "/design", "/auth/confirm"])(
    "leaves the public page %s alone for signed-out visitors",
    async (path) => {
      claims.getClaims.mockResolvedValue({ data: null });

      const response = await updateSession(request(path));

      expect(response.status).toBe(200);
    },
  );

  it("treats claims without a subject as signed out", async () => {
    claims.getClaims.mockResolvedValue({ data: { claims: {} } });

    const response = await updateSession(request("/dashboard"));

    expect(response.status).toBe(307);
  });

  it("writes refreshed session cookies as HttpOnly so page scripts cannot read them", async () => {
    claims.getClaims.mockImplementation(async () => {
      // What @supabase/ssr does when it refreshes an expiring session.
      captured.cookies?.setAll(
        [
          {
            name: "sb-abcd-auth-token",
            value: "refreshed",
            options: { path: "/", httpOnly: false },
          },
        ],
        { "Cache-Control": "private, no-cache, no-store, must-revalidate" },
      );
      return { data: { claims: { sub: "u1" } } };
    });

    const response = await updateSession(request("/dashboard"));

    const setCookie = response.headers.get("set-cookie") ?? "";
    expect(setCookie).toContain("sb-abcd-auth-token=refreshed");
    expect(setCookie).toMatch(/HttpOnly/i);
    expect(setCookie).toMatch(/SameSite=lax/i);
    // The cache headers that stop a CDN serving one user's session to another must survive.
    expect(response.headers.get("cache-control")).toContain("no-store");
  });

  it("keeps hardened cookies on the redirect for a signed-out visitor", async () => {
    claims.getClaims.mockImplementation(async () => {
      captured.cookies?.setAll(
        [{ name: "sb-abcd-auth-token", value: "", options: { path: "/", maxAge: 0 } }],
        {},
      );
      return { data: null };
    });

    const response = await updateSession(request("/dashboard"));

    expect(response.status).toBe(307);
    expect(response.headers.get("set-cookie") ?? "").toMatch(/HttpOnly/i);
  });

  it("does nothing when Supabase is not configured (development)", async () => {
    config.value = null;

    const response = await updateSession(request("/dashboard"));

    expect(response.status).toBe(200);
    expect(claims.getClaims).not.toHaveBeenCalled();
  });
});

describe("updateSession with a confirmation code on the landing page", () => {
  const CODE = "c095dca5-53b7-4574-925a-243491f08a72";

  it("forwards Supabase's /?code= link to the confirm route and the first-run setup", async () => {
    const response = await updateSession(request(`/?code=${CODE}`));

    expect(response.status).toBe(307);
    const location = new URL(response.headers.get("location") ?? "");
    expect(location.pathname).toBe("/auth/confirm");
    expect(location.searchParams.get("code")).toBe(CODE);
    expect(location.searchParams.get("next")).toBe("/onboarding");
    expect(claims.getClaims).not.toHaveBeenCalled();
  });

  it("forwards nothing else from the landing page's query", async () => {
    const response = await updateSession(request(`/?code=${CODE}&next=https://evil.example&x=1`));

    const location = new URL(response.headers.get("location") ?? "");
    expect([...location.searchParams.keys()].sort()).toEqual(["code", "next"]);
    expect(location.searchParams.get("next")).toBe("/onboarding");
  });

  it.each(["", "short", "a b c d e f g h", "<img src=x>", "x".repeat(200)])(
    "leaves the landing page alone for the odd code %j",
    async (code) => {
      claims.getClaims.mockResolvedValue({ data: null });

      const response = await updateSession(request(`/?code=${encodeURIComponent(code)}`));

      expect(response.status).toBe(200);
      expect(response.headers.get("location")).toBeNull();
    },
  );

  it("only the landing page forwards: a code on another page is just a parameter there", async () => {
    claims.getClaims.mockResolvedValue({ data: null });

    const response = await updateSession(request(`/status?code=${CODE}`));

    expect(response.status).toBe(200);
  });
});
