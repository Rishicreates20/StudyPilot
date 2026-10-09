import { z } from "zod";

import { getServerEnv } from "@/lib/env";

const healthSchema = z.object({
  status: z.literal("ok"),
  service: z.string(),
  version: z.string(),
});

const readinessSchema = z.object({
  status: z.enum(["ready", "unavailable"]),
  checks: z.record(z.string(), z.enum(["ok", "fail"])),
});

export type ApiStatus =
  | {
      state: "up";
      service: string;
      version: string;
      ready: boolean;
      checks: Readonly<Record<string, "ok" | "fail">>;
      latencyMs: number;
    }
  | { state: "unreachable"; reason: "timeout" | "network" | "bad-response" };

const DEFAULT_TIMEOUT_MS = 3000;

type Fetcher = (input: string, init?: RequestInit) => Promise<Response>;

/**
 * Ask the API about its own health. Runs on the server (it uses the internal API URL) and
 * reports honestly when the API cannot be reached; it never invents a "healthy" answer.
 */
export async function fetchApiStatus(
  fetcher: Fetcher = fetch,
  timeoutMs: number = DEFAULT_TIMEOUT_MS,
): Promise<ApiStatus> {
  const base = getServerEnv().API_INTERNAL_BASE_URL;
  const request = (path: string) =>
    fetcher(`${base}${path}`, {
      cache: "no-store",
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(timeoutMs),
    });

  const started = performance.now();
  try {
    const [healthResponse, readinessResponse] = await Promise.all([
      request("/healthz"),
      request("/readyz"),
    ]);
    const latencyMs = Math.round(performance.now() - started);

    const health = healthSchema.safeParse(await healthResponse.json());
    // /readyz answers 503 with a valid body when a dependency is down, so the body is parsed
    // regardless of status code.
    const readiness = readinessSchema.safeParse(await readinessResponse.json());
    if (!healthResponse.ok || !health.success || !readiness.success) {
      return { state: "unreachable", reason: "bad-response" };
    }
    return {
      state: "up",
      service: health.data.service,
      version: health.data.version,
      ready: readiness.data.status === "ready",
      checks: readiness.data.checks,
      latencyMs,
    };
  } catch (error) {
    if (error instanceof DOMException && error.name === "TimeoutError") {
      return { state: "unreachable", reason: "timeout" };
    }
    return {
      state: "unreachable",
      reason: error instanceof SyntaxError ? "bad-response" : "network",
    };
  }
}
