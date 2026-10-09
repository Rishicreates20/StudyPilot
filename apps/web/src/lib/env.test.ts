import { describe, expect, it } from "vitest";

import { EnvValidationError, parsePublicEnv, parseServerEnv } from "@/lib/env";

describe("parsePublicEnv", () => {
  it("falls back to local defaults when defaults are allowed", () => {
    expect(parsePublicEnv({}, true)).toEqual({
      NEXT_PUBLIC_APP_NAME: "StudyPilot",
      NEXT_PUBLIC_API_BASE_URL: "http://localhost:8000",
    });
  });

  it("treats blank values as missing", () => {
    const env = parsePublicEnv({ NEXT_PUBLIC_APP_NAME: "  ", NEXT_PUBLIC_API_BASE_URL: "" }, true);

    expect(env.NEXT_PUBLIC_APP_NAME).toBe("StudyPilot");
    expect(env.NEXT_PUBLIC_API_BASE_URL).toBe("http://localhost:8000");
  });

  it("requires an explicit API URL when defaults are not allowed (production)", () => {
    expect(() => parsePublicEnv({}, false)).toThrow(EnvValidationError);
    expect(() => parsePublicEnv({}, false)).toThrow(/NEXT_PUBLIC_API_BASE_URL: is required/);
  });

  it("strips trailing slashes so paths can be appended safely", () => {
    const env = parsePublicEnv({ NEXT_PUBLIC_API_BASE_URL: "https://api.example.com//" }, false);

    expect(env.NEXT_PUBLIC_API_BASE_URL).toBe("https://api.example.com");
  });

  it("rejects non-http(s) URLs", () => {
    expect(() => parsePublicEnv({ NEXT_PUBLIC_API_BASE_URL: "ftp://example.com" }, false)).toThrow(
      EnvValidationError,
    );
  });

  it("names the broken variable without echoing its value", () => {
    const secretLooking = "not-a-url-s3cr3t-value";
    try {
      parsePublicEnv({ NEXT_PUBLIC_API_BASE_URL: secretLooking }, false);
      expect.unreachable("expected validation to fail");
    } catch (error) {
      expect(error).toBeInstanceOf(EnvValidationError);
      const message = (error as EnvValidationError).message;
      expect(message).toContain("NEXT_PUBLIC_API_BASE_URL: must be an http(s) URL");
      expect(message).not.toContain(secretLooking);
    }
  });
});

describe("parseServerEnv", () => {
  it("uses the public API URL for server-side calls by default", () => {
    const env = parseServerEnv({ NEXT_PUBLIC_API_BASE_URL: "https://api.example.com" }, false);

    expect(env.API_INTERNAL_BASE_URL).toBe("https://api.example.com");
  });

  it("prefers the internal API URL when provided", () => {
    const env = parseServerEnv(
      {
        NEXT_PUBLIC_API_BASE_URL: "http://localhost:8000",
        API_INTERNAL_BASE_URL: "http://api:8000/",
      },
      false,
    );

    expect(env.API_INTERNAL_BASE_URL).toBe("http://api:8000");
    expect(env.NEXT_PUBLIC_API_BASE_URL).toBe("http://localhost:8000");
  });

  it("reports an invalid internal URL", () => {
    expect(() =>
      parseServerEnv(
        { NEXT_PUBLIC_API_BASE_URL: "http://localhost:8000", API_INTERNAL_BASE_URL: "nope" },
        false,
      ),
    ).toThrow(/API_INTERNAL_BASE_URL/);
  });
});

describe("URL validation", () => {
  it.each(["http://localhost:8000", "http://api:8000", "https://api.example.com"])(
    "accepts %s, a value used in development or deployment",
    (url) => {
      expect(
        parsePublicEnv({ NEXT_PUBLIC_API_BASE_URL: url }, false).NEXT_PUBLIC_API_BASE_URL,
      ).toBe(url);
    },
  );
});
