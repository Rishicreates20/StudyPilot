import { describe, expect, it } from "vitest";

import { signInErrorMessage, signUpErrorMessage } from "@/lib/auth/messages";

describe("signInErrorMessage", () => {
  it("gives one answer for a wrong password and an unknown email", () => {
    // Both arrive from Supabase as invalid_credentials; the UI must not tell them apart.
    expect(signInErrorMessage({ code: "invalid_credentials" })).toBe(
      "The email or password is incorrect.",
    );
  });

  it("tells unconfirmed users what to do", () => {
    expect(signInErrorMessage({ code: "email_not_confirmed" })).toMatch(/confirm your email/i);
  });

  it("explains rate limiting", () => {
    expect(signInErrorMessage({ code: "over_request_rate_limit" })).toMatch(/too many attempts/i);
  });

  it.each([undefined, "unexpected_failure", "some_new_code"])(
    "falls back to a generic message for %s, never the provider's text",
    (code) => {
      const message = signInErrorMessage({ code });
      expect(message).toMatch(/something went wrong/i);
      expect(message).not.toContain(String(code));
    },
  );
});

describe("signUpErrorMessage", () => {
  it.each(["user_already_exists", "email_exists"])("%s suggests signing in", (code) => {
    expect(signUpErrorMessage({ code })).toMatch(/may already exist/i);
  });

  it("explains weak passwords", () => {
    expect(signUpErrorMessage({ code: "weak_password" })).toMatch(/too easy to guess/i);
  });

  it("reports closed sign-ups", () => {
    expect(signUpErrorMessage({ code: "signup_disabled" })).toMatch(/closed/i);
  });

  it("falls back to a generic message", () => {
    expect(signUpErrorMessage({ code: "mystery" })).toMatch(/something went wrong/i);
  });
});
