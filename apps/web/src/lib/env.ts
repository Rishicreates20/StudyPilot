/**
 * Environment validation for the web app.
 *
 * - `NEXT_PUBLIC_*` variables are inlined into the browser bundle at build time, so they must
 *   never hold secrets. They are read through literal `process.env.NAME` accesses below
 *   because Next.js can only inline those.
 * - Server-only variables (no prefix) are read at runtime and never reach the browser.
 * - Development and tests fall back to local defaults. Production builds and servers require
 *   explicit values so a misconfigured deployment fails loudly instead of pointing at localhost.
 *
 * Validation errors name the variable and the problem but never echo the supplied value.
 */
import { z } from "zod";

type RawEnv = Readonly<Record<string, string | undefined>>;

const DEFAULT_APP_NAME = "StudyPilot";
const DEFAULT_API_BASE_URL = "http://localhost:8000";

const blankToUndefined = (value: unknown) =>
  typeof value === "string" && value.trim() === "" ? undefined : value;
const withoutTrailingSlash = (url: string) => url.replace(/\/+$/, "");

// Not z.httpUrl(): it demands a dotted hostname and would reject http://localhost:8000 and the
// Docker service name http://api:8000, which are exactly the values used in development.
const httpUrl = () =>
  z
    .url({
      protocol: /^https?$/,
      // Only reads `issue.input` to tell "missing" from "malformed"; the value is never echoed.
      error: (issue) =>
        issue.input === undefined
          ? "is required (an http(s) URL, for example https://api.example.com)"
          : "must be an http(s) URL",
    })
    .transform(withoutTrailingSlash);

function publicSchema(allowDefaults: boolean) {
  return z.object({
    NEXT_PUBLIC_APP_NAME: z.preprocess(
      blankToUndefined,
      z.string().trim().min(1).max(60).default(DEFAULT_APP_NAME),
    ),
    NEXT_PUBLIC_API_BASE_URL: z.preprocess(
      blankToUndefined,
      allowDefaults ? httpUrl().default(DEFAULT_API_BASE_URL) : httpUrl(),
    ),
  });
}

const serverOnlySchema = z.object({
  /** Where server-side code reaches the API (for example the Docker service name). */
  API_INTERNAL_BASE_URL: z.preprocess(blankToUndefined, httpUrl().optional()),
});

export type PublicEnv = z.output<ReturnType<typeof publicSchema>>;
export type ServerEnv = PublicEnv & { API_INTERNAL_BASE_URL: string };

export class EnvValidationError extends Error {
  readonly issues: readonly string[];

  constructor(issues: readonly string[]) {
    super(["Invalid environment configuration:", ...issues.map((i) => `  - ${i}`)].join("\n"));
    this.name = "EnvValidationError";
    this.issues = issues;
  }
}

function issuesOf(error: z.ZodError): string[] {
  return error.issues.map((issue) => `${issue.path.join(".") || "env"}: ${issue.message}`);
}

const isProduction = () => process.env.NODE_ENV === "production";

export function parsePublicEnv(raw: RawEnv, allowDefaults: boolean = !isProduction()): PublicEnv {
  const result = publicSchema(allowDefaults).safeParse(raw);
  if (!result.success) throw new EnvValidationError(issuesOf(result.error));
  return result.data;
}

export function parseServerEnv(raw: RawEnv, allowDefaults: boolean = !isProduction()): ServerEnv {
  const publicResult = publicSchema(allowDefaults).safeParse(raw);
  const serverResult = serverOnlySchema.safeParse(raw);
  const issues = [
    ...(publicResult.success ? [] : issuesOf(publicResult.error)),
    ...(serverResult.success ? [] : issuesOf(serverResult.error)),
  ];
  if (!publicResult.success || !serverResult.success || issues.length > 0) {
    throw new EnvValidationError(issues);
  }
  return {
    ...publicResult.data,
    API_INTERNAL_BASE_URL:
      serverResult.data.API_INTERNAL_BASE_URL ?? publicResult.data.NEXT_PUBLIC_API_BASE_URL,
  };
}

// Literal property accesses are required for Next.js to inline NEXT_PUBLIC_* values.
const readRawEnv = (): RawEnv => ({
  NEXT_PUBLIC_APP_NAME: process.env.NEXT_PUBLIC_APP_NAME,
  NEXT_PUBLIC_API_BASE_URL: process.env.NEXT_PUBLIC_API_BASE_URL,
  API_INTERNAL_BASE_URL: process.env.API_INTERNAL_BASE_URL,
});

let cachedPublic: PublicEnv | undefined;
let cachedServer: ServerEnv | undefined;

export function getPublicEnv(): PublicEnv {
  cachedPublic ??= parsePublicEnv(readRawEnv());
  return cachedPublic;
}

/** Server-only: includes variables that must not be exposed to the browser. */
export function getServerEnv(): ServerEnv {
  if (typeof window !== "undefined") {
    throw new Error("getServerEnv() must not be called in the browser.");
  }
  cachedServer ??= parseServerEnv(readRawEnv());
  return cachedServer;
}

/** Called once at server start (see instrumentation.ts) so bad configuration fails fast. */
export function validateEnv(): void {
  getServerEnv();
}
