import { defineConfig, devices } from "@playwright/test";

/**
 * Browser tests of the real sign-up -> goal -> sign-out flow.
 *
 * They need a Supabase stack (CI starts one with `npx supabase start`) and read the same settings
 * the apps do, so export them first: NEXT_PUBLIC_SUPABASE_URL, NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY,
 * NEXT_PUBLIC_API_BASE_URL (all before `npm run build`), plus DATABASE_URL, SUPABASE_URL and, for
 * legacy HS256 stacks, SUPABASE_JWT_MODE / SUPABASE_JWT_SECRET for the API.
 * `.github/scripts/supabase_stack_env.py` prints all of them for a running local stack.
 *
 * Playwright starts the built web app, the API and the background worker itself; run
 * `npm run build` beforehand.
 */
const webUrl = process.env.E2E_WEB_URL ?? "http://127.0.0.1:3000";
const apiUrl = process.env.E2E_API_URL ?? "http://127.0.0.1:8000";

/**
 * These tests create real accounts, goals and background jobs. They must never run against a
 * hosted project, and the API and worker would otherwise quietly fall back to whatever
 * `services/api/.env` holds (usually a real project). So the stack must be on this machine and
 * must be named explicitly in the environment; anything else stops here, before a server starts.
 */
const LOOPBACK_HOSTS = new Set(["127.0.0.1", "localhost", "[::1]", "::1"]);
function isLoopback(value: string | undefined): boolean {
  if (!value) return false;
  try {
    return LOOPBACK_HOSTS.has(new URL(value).hostname);
  } catch {
    return false;
  }
}
for (const name of ["NEXT_PUBLIC_SUPABASE_URL", "SUPABASE_URL", "DATABASE_URL"]) {
  if (!isLoopback(process.env[name])) {
    throw new Error(
      `${name} must be set to a Supabase stack running on this machine (127.0.0.1 or localhost) ` +
        "before running the browser tests, so they cannot touch a hosted project. " +
        "`.github/scripts/supabase_stack_env.py` prints the values for `npx supabase start`.",
    );
  }
}

export default defineConfig({
  testDir: "./e2e",
  testMatch: "**/*.e2e.ts",
  // The scenarios build on each other (one account, one session), so run them in order.
  fullyParallel: false,
  workers: 1,
  retries: 0,
  // A cold server's first render of a page, or a CI runner's first browser launch, can take a few
  // seconds. Generous waits cost nothing when things are fast; retries would hide real flakiness.
  timeout: 60_000,
  expect: { timeout: 15_000 },
  forbidOnly: Boolean(process.env.CI),
  reporter: process.env.CI ? [["list"], ["github"]] : "list",
  use: {
    baseURL: webUrl,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command:
        "uv run --directory ../../services/api python -m uvicorn app.main:create_app --factory --loop asyncio:SelectorEventLoop --port 8000 --no-access-log",
      url: `${apiUrl}/readyz`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      // The API only checks that an AI provider is configured; the built-in test provider labels
      // everything it makes as a sample, so these tests never call a real model.
      env: { LLM_PROVIDER: "fake" },
    },
    {
      // Runs the queued roadmap jobs. It has no port, so Playwright waits for its start-up line.
      command: "uv run --directory ../../services/api python -m app.worker",
      wait: { stdout: /worker\.started/ },
      timeout: 120_000,
      env: { LLM_PROVIDER: "fake", WORKER_POLL_SECONDS: "1", JOB_RETRY_BASE_SECONDS: "1" },
    },
    {
      command: "npm run start -- --hostname 127.0.0.1",
      url: `${webUrl}/api/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: { API_INTERNAL_BASE_URL: apiUrl },
    },
  ],
});
