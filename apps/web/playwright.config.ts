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
 * Playwright starts the built web app and the API itself; run `npm run build` beforehand.
 */
const webUrl = process.env.E2E_WEB_URL ?? "http://127.0.0.1:3000";
const apiUrl = process.env.E2E_API_URL ?? "http://127.0.0.1:8000";

export default defineConfig({
  testDir: "./e2e",
  testMatch: "**/*.e2e.ts",
  // The scenarios build on each other (one account, one session), so run them in order.
  fullyParallel: false,
  workers: 1,
  retries: 0,
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
