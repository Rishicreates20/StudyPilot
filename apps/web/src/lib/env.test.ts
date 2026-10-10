import { describe, expect, it } from "vitest";

import { EnvValidationError, parsePublicEnv, parseServerEnv, supabaseConfigOf } from "@/lib/env";

/** A complete Supabase configuration, as production requires. */
const SUPABASE = {
  NEXT_PUBLIC_SUPABASE_URL: "https://abcd.supabase.co",
  NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: "sb_publishable_abcdefghijklmnop",
} as const;

describe("parsePublicEnv", () => {
  it("falls back to local defaults when defaults are allowed", () => {
    expect(parsePublicEnv({}, true)).toEqual({
      NEXT_PUBLIC_APP_NAME: "StudyPilot",
      NEXT_PUBLIC_API_BASE_URL: "http://localhost:8000",
      NEXT_PUBLIC_SUPABASE_URL: undefined,
      NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: undefined,
    });
  });

  it("treats blank values as missing", () => {
    const env = parsePublicEnv(
      {
        NEXT_PUBLIC_APP_NAME: "  ",
        NEXT_PUBLIC_API_BASE_URL: "",
        NEXT_PUBLIC_SUPABASE_URL: "",
        NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: "  ",
      },
      true,
    );

    expect(env.NEXT_PUBLIC_APP_NAME).toBe("StudyPilot");
    expect(env.NEXT_PUBLIC_API_BASE_URL).toBe("http://localhost:8000");
    expect(env.NEXT_PUBLIC_SUPABASE_URL).toBeUndefined();
  });

  it("requires an explicit API URL when defaults are not allowed (production)", () => {
    expect(() => parsePublicEnv({ ...SUPABASE }, false)).toThrow(EnvValidationError);
    expect(() => parsePublicEnv({ ...SUPABASE }, false)).toThrow(
      /NEXT_PUBLIC_API_BASE_URL: is required/,
    );
  });

  it("strips trailing slashes so paths can be appended safely", () => {
    const env = parsePublicEnv(
      { ...SUPABASE, NEXT_PUBLIC_API_BASE_URL: "https://api.example.com//" },
      false,
    );

    expect(env.NEXT_PUBLIC_API_BASE_URL).toBe("https://api.example.com");
  });

  it("rejects non-http(s) URLs", () => {
    expect(() =>
      parsePublicEnv({ ...SUPABASE, NEXT_PUBLIC_API_BASE_URL: "ftp://example.com" }, false),
    ).toThrow(EnvValidationError);
  });

  it("names the broken variable without echoing its value", () => {
    const secretLooking = "not-a-url-s3cr3t-value";
    try {
      parsePublicEnv({ ...SUPABASE, NEXT_PUBLIC_API_BASE_URL: secretLooking }, false);
      expect.unreachable("expected validation to fail");
    } catch (error) {
      expect(error).toBeInstanceOf(EnvValidationError);
      const message = (error as EnvValidationError).message;
      expect(message).toContain("NEXT_PUBLIC_API_BASE_URL: must be an http(s) URL");
      expect(message).not.toContain(secretLooking);
    }
  });
});

describe("Supabase configuration", () => {
  const api = { NEXT_PUBLIC_API_BASE_URL: "https://api.example.com" };

  it("is optional in development, and then reported as not configured", () => {
    const env = parsePublicEnv({}, true);

    expect(supabaseConfigOf(env)).toBeNull();
  });

  it("is required in production", () => {
    expect(() => parsePublicEnv(api, false)).toThrow(/NEXT_PUBLIC_SUPABASE_URL: is required/);
    expect(() => parsePublicEnv(api, false)).toThrow(
      /NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: is required/,
    );
  });

  it("yields the project URL and publishable key when both are set", () => {
    const env = parsePublicEnv({ ...api, ...SUPABASE }, false);

    expect(supabaseConfigOf(env)).toEqual({
      url: "https://abcd.supabase.co",
      publishableKey: "sb_publishable_abcdefghijklmnop",
    });
  });

  it("insists on both values even in development: a half-configured project is a mistake", () => {
    expect(() =>
      parsePublicEnv({ NEXT_PUBLIC_SUPABASE_URL: SUPABASE.NEXT_PUBLIC_SUPABASE_URL }, true),
    ).toThrow(/NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: is required together/);
    expect(() =>
      parsePublicEnv(
        { NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: SUPABASE.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY },
        true,
      ),
    ).toThrow(/NEXT_PUBLIC_SUPABASE_URL: is required together/);
  });

  it("accepts the local Supabase CLI address", () => {
    const env = parsePublicEnv(
      { ...SUPABASE, NEXT_PUBLIC_SUPABASE_URL: "http://127.0.0.1:54321" },
      true,
    );

    expect(env.NEXT_PUBLIC_SUPABASE_URL).toBe("http://127.0.0.1:54321");
  });

  it("rejects a key that is obviously not one, without echoing it", () => {
    const tooShort = "abc";
    try {
      parsePublicEnv({ ...SUPABASE, NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: tooShort }, true);
      expect.unreachable("expected validation to fail");
    } catch (error) {
      const message = (error as EnvValidationError).message;
      expect(message).toContain("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY");
      expect(message).not.toContain(`"${tooShort}"`);
    }
  });
});

describe("parseServerEnv", () => {
  const production = { ...SUPABASE };

  it("uses the public API URL for server-side calls by default", () => {
    const env = parseServerEnv(
      { ...production, NEXT_PUBLIC_API_BASE_URL: "https://api.example.com" },
      false,
    );

    expect(env.API_INTERNAL_BASE_URL).toBe("https://api.example.com");
  });

  it("prefers the internal API URL when provided", () => {
    const env = parseServerEnv(
      {
        ...production,
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
        {
          ...production,
          NEXT_PUBLIC_API_BASE_URL: "http://localhost:8000",
          API_INTERNAL_BASE_URL: "nope",
        },
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
        parsePublicEnv({ ...SUPABASE, NEXT_PUBLIC_API_BASE_URL: url }, false)
          .NEXT_PUBLIC_API_BASE_URL,
      ).toBe(url);
    },
  );
});
