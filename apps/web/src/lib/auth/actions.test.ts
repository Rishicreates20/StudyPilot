// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest";

const auth = vi.hoisted(() => ({
  signInWithPassword: vi.fn(),
  signUp: vi.fn(),
  signOut: vi.fn(),
}));
const supabase = vi.hoisted(() => ({ current: null as unknown }));

vi.mock("next/navigation", () => ({
  redirect: (url: string) => {
    throw new Error(`REDIRECT:${url}`);
  },
}));
vi.mock("@/lib/supabase/server", () => ({
  createClient: async () => supabase.current,
}));

import { signInAction, signOutAction, signUpAction } from "@/lib/auth/actions";

function form(fields: Record<string, string>): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(fields)) data.set(key, value);
  return data;
}

const idle = { status: "idle" } as const;

beforeEach(() => {
  vi.clearAllMocks();
  supabase.current = { auth };
});

describe("signInAction", () => {
  const credentials = { email: "ada@example.com", password: "correct horse battery", next: "" };

  it("signs in and redirects to the dashboard by default", async () => {
    auth.signInWithPassword.mockResolvedValue({ error: null });

    await expect(signInAction(idle, form(credentials))).rejects.toThrow("REDIRECT:/dashboard");
    expect(auth.signInWithPassword).toHaveBeenCalledWith({
      email: "ada@example.com",
      password: "correct horse battery",
    });
  });

  it("returns to the page the visitor came from", async () => {
    auth.signInWithPassword.mockResolvedValue({ error: null });

    await expect(signInAction(idle, form({ ...credentials, next: "/goals/new" }))).rejects.toThrow(
      "REDIRECT:/goals/new",
    );
  });

  it.each(["https://evil.example", "//evil.example", "/\\evil.example", "javascript:alert(1)"])(
    "will not be redirected off-site via next=%s",
    async (next) => {
      auth.signInWithPassword.mockResolvedValue({ error: null });

      await expect(signInAction(idle, form({ ...credentials, next }))).rejects.toThrow(
        "REDIRECT:/dashboard",
      );
    },
  );

  it("gives field errors without contacting Supabase when the input is malformed", async () => {
    const state = await signInAction(idle, form({ email: "nope", password: "" }));

    expect(auth.signInWithPassword).not.toHaveBeenCalled();
    expect(state).toMatchObject({
      status: "error",
      fieldErrors: { email: expect.any(String), password: expect.any(String) },
    });
  });

  it("uses one message for wrong credentials and never returns the password", async () => {
    auth.signInWithPassword.mockResolvedValue({ error: { code: "invalid_credentials" } });

    const state = await signInAction(idle, form(credentials));

    expect(state).toEqual({
      status: "error",
      formError: "The email or password is incorrect.",
      fieldErrors: {},
      values: { email: "ada@example.com" },
    });
    expect(JSON.stringify(state)).not.toContain("correct horse battery");
  });

  it("does not leak provider error text", async () => {
    auth.signInWithPassword.mockResolvedValue({
      error: { code: "unexpected", message: "internal: db host 10.0.0.5 refused" },
    });

    const state = await signInAction(idle, form(credentials));

    expect(JSON.stringify(state)).not.toContain("10.0.0.5");
  });

  it("explains when sign-in is not configured instead of failing", async () => {
    supabase.current = null;

    const state = await signInAction(idle, form(credentials));

    expect(state).toMatchObject({
      status: "error",
      formError: expect.stringContaining("not configured"),
    });
  });
});

describe("signUpAction", () => {
  const details = {
    displayName: "Ada",
    email: "ada@example.com",
    password: "correct horse battery",
  };

  it("creates the account with the display name as profile metadata", async () => {
    auth.signUp.mockResolvedValue({ data: { session: { access_token: "x" } }, error: null });

    await expect(signUpAction(idle, form(details))).rejects.toThrow("REDIRECT:/dashboard");
    expect(auth.signUp).toHaveBeenCalledWith({
      email: "ada@example.com",
      password: "correct horse battery",
      options: { data: { display_name: "Ada" } },
    });
  });

  it("sends no metadata when no name is given", async () => {
    auth.signUp.mockResolvedValue({ data: { session: { access_token: "x" } }, error: null });

    await expect(signUpAction(idle, form({ ...details, displayName: "" }))).rejects.toThrow(
      "REDIRECT",
    );
    expect(auth.signUp.mock.calls[0]?.[0].options).toEqual({ data: {} });
  });

  it("asks the user to confirm their email when no session is returned", async () => {
    auth.signUp.mockResolvedValue({ data: { session: null }, error: null });

    const state = await signUpAction(idle, form(details));

    expect(state).toEqual({ status: "check-email", email: "ada@example.com" });
  });

  it("rejects a short password before contacting Supabase", async () => {
    const state = await signUpAction(idle, form({ ...details, password: "short" }));

    expect(auth.signUp).not.toHaveBeenCalled();
    expect(state).toMatchObject({ status: "error", fieldErrors: { password: expect.any(String) } });
  });

  it("keeps what the user typed, but never the password", async () => {
    auth.signUp.mockResolvedValue({ data: { session: null }, error: { code: "weak_password" } });

    const state = await signUpAction(idle, form(details));

    expect(state).toMatchObject({
      status: "error",
      values: { displayName: "Ada", email: "ada@example.com" },
    });
    expect(JSON.stringify(state)).not.toContain("correct horse battery");
  });

  it("maps provider errors to safe messages", async () => {
    auth.signUp.mockResolvedValue({ data: { session: null }, error: { code: "signup_disabled" } });

    const state = await signUpAction(idle, form(details));

    expect(state).toMatchObject({ formError: expect.stringMatching(/closed/i) });
  });
});

describe("signOutAction", () => {
  it("ends only this device's session and returns to the landing page", async () => {
    auth.signOut.mockResolvedValue({ error: null });

    await expect(signOutAction()).rejects.toThrow("REDIRECT:/");
    expect(auth.signOut).toHaveBeenCalledWith({ scope: "local" });
  });

  it("still returns to the landing page when Supabase is not configured", async () => {
    supabase.current = null;

    await expect(signOutAction()).rejects.toThrow("REDIRECT:/");
  });
});
