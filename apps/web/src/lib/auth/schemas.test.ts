import { describe, expect, it } from "vitest";

import { signInSchema, signUpSchema } from "@/lib/auth/schemas";
import { zodFieldErrors } from "@/lib/forms";

describe("signInSchema", () => {
  it("accepts an email and any non-empty password, trimming the email", () => {
    const result = signInSchema.safeParse({ email: "  ada@example.com ", password: "x" });

    expect(result.success && result.data).toEqual({ email: "ada@example.com", password: "x" });
  });

  it("does not trim or limit the password (existing accounts must still sign in)", () => {
    const password = "  spaces and a long tail ".padEnd(200, "z");

    const result = signInSchema.safeParse({ email: "ada@example.com", password });

    expect(result.success && result.data.password).toBe(password);
  });

  it.each(["", "not-an-email", "a@", "@b.com", "a b@c.com"])("rejects the email %j", (email) => {
    const result = signInSchema.safeParse({ email, password: "secret" });

    expect(result.success).toBe(false);
    if (!result.success) expect(zodFieldErrors(result.error).email).toBeDefined();
  });

  it("requires a password", () => {
    const result = signInSchema.safeParse({ email: "ada@example.com", password: "" });

    expect(result.success).toBe(false);
    if (!result.success)
      expect(zodFieldErrors(result.error)).toEqual({ password: "Enter your password." });
  });
});

describe("signUpSchema", () => {
  const valid = { displayName: "Ada", email: "ada@example.com", password: "correct horse battery" };

  it("accepts a complete, valid sign-up", () => {
    expect(signUpSchema.safeParse(valid).success).toBe(true);
  });

  it("allows an empty display name", () => {
    expect(signUpSchema.safeParse({ ...valid, displayName: "" }).success).toBe(true);
  });

  it("enforces the minimum password length", () => {
    const short = signUpSchema.safeParse({ ...valid, password: "a".repeat(9) });
    const exact = signUpSchema.safeParse({ ...valid, password: "a".repeat(10) });

    expect(short.success).toBe(false);
    expect(exact.success).toBe(true);
  });

  it("refuses passwords the identity provider would silently truncate", () => {
    const result = signUpSchema.safeParse({ ...valid, password: "a".repeat(73) });

    expect(result.success).toBe(false);
  });

  it("limits the display name", () => {
    expect(signUpSchema.safeParse({ ...valid, displayName: "n".repeat(81) }).success).toBe(false);
  });

  it("reports every failing field at once", () => {
    const result = signUpSchema.safeParse({ displayName: "", email: "nope", password: "short" });

    expect(result.success).toBe(false);
    if (!result.success) {
      expect(Object.keys(zodFieldErrors(result.error)).sort()).toEqual(["email", "password"]);
    }
  });
});
