import { describe, expect, it } from "vitest";

import {
  isProtectedPath,
  safeRedirectPath,
  sessionEndedUrlFor,
  signInUrlFor,
} from "@/lib/auth/paths";

describe("safeRedirectPath", () => {
  it.each(["/dashboard", "/goals/new", "/dashboard?cursor=abc", "/a/b/c?x=1#frag", "/"])(
    "keeps the same-site destination %s",
    (path) => {
      expect(safeRedirectPath(path)).toBe(path);
    },
  );

  it.each([
    ["an absolute URL", "https://evil.example/phish"],
    ["a protocol-relative URL", "//evil.example"],
    ["a protocol-relative URL with a path", "//evil.example/dashboard"],
    ["a backslash trick", "/\\evil.example"],
    ["an embedded backslash", "/dashboard\\..\\x"],
    ["a javascript: URL", "javascript:alert(1)"],
    ["a data: URL", "data:text/html,<script>1</script>"],
    ["a scheme without slashes", "https:evil.example"],
    ["a path not starting with a slash", "dashboard"],
    ["a CRLF injection", "/dashboard\r\nSet-Cookie: a=b"],
    ["a tab", "/da\tshboard"],
    ["a NUL byte", "/dashboard\u0000"],
    ["an empty string", ""],
    ["a very long string", `/${"a".repeat(600)}`],
  ])("refuses %s", (_label, candidate) => {
    expect(safeRedirectPath(candidate)).toBe("/dashboard");
  });

  it.each([undefined, null, 42, {}, ["/dashboard"], true])("refuses a non-string (%j)", (value) => {
    expect(safeRedirectPath(value)).toBe("/dashboard");
  });

  it("uses the supplied fallback", () => {
    expect(safeRedirectPath("//evil.example", "/")).toBe("/");
  });
});

describe("isProtectedPath", () => {
  it.each(["/dashboard", "/dashboard/anything", "/goals", "/goals/new", "/goals/123/edit"])(
    "%s needs a session",
    (path) => {
      expect(isProtectedPath(path)).toBe(true);
    },
  );

  it.each([
    "/",
    "/sign-in",
    "/sign-up",
    "/status",
    "/design",
    "/auth/confirm",
    "/dashboards",
    "/goalsetting",
  ])("%s is public", (path) => {
    expect(isProtectedPath(path)).toBe(false);
  });
});

describe("signInUrlFor", () => {
  it("returns to the page the visitor wanted", () => {
    expect(signInUrlFor("/goals/new")).toBe("/sign-in?next=%2Fgoals%2Fnew");
  });

  it("encodes query strings so they cannot add parameters", () => {
    expect(signInUrlFor("/dashboard?cursor=a&next=//evil.example")).toBe(
      "/sign-in?next=%2Fdashboard%3Fcursor%3Da%26next%3D%2F%2Fevil.example",
    );
  });

  it("never carries an unsafe destination", () => {
    expect(signInUrlFor("https://evil.example")).toBe("/sign-in?next=%2Fdashboard");
  });
});

describe("sessionEndedUrlFor", () => {
  it("is the normal sign-in URL plus a marker the sign-in page can recognise", () => {
    expect(sessionEndedUrlFor("/dashboard")).toBe("/sign-in?next=%2Fdashboard&error=session_ended");
  });

  it("is still a same-site URL whatever destination it is given", () => {
    expect(sessionEndedUrlFor("https://evil.example")).toBe(
      "/sign-in?next=%2Fdashboard&error=session_ended",
    );
  });
});
