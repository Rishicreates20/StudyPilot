import { randomUUID } from "node:crypto";

import { expect, test, type Browser, type Page } from "@playwright/test";

/**
 * The acceptance scenario for authentication, in a real browser against real Supabase Auth:
 * create an account, stay signed in, own data, sign out, sign back in, and never see another
 * user's data. Nothing here fakes a session: every cookie is set by Supabase through the app.
 */

const API_URL = process.env.E2E_API_URL ?? "http://127.0.0.1:8000";

function newLearner(label: string) {
  const suffix = randomUUID().slice(0, 8);
  return {
    name: `Learner ${label}`,
    email: `e2e-${label}-${suffix}@example.test`,
    password: `Pw-${randomUUID()}`,
  };
}

type Learner = ReturnType<typeof newLearner>;

async function signUp(page: Page, learner: Learner) {
  await page.goto("/sign-up");
  await page.getByLabel("Your name").fill(learner.name);
  await page.getByLabel("Email").fill(learner.email);
  await page.getByLabel("Password", { exact: true }).fill(learner.password);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
}

async function signIn(page: Page, learner: Learner, password = learner.password) {
  await page.goto("/sign-in");
  await page.getByLabel("Email").fill(learner.email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
}

async function createGoal(page: Page, title: string) {
  await page.goto("/goals/new");
  await page.getByLabel("What do you want to learn?").fill(title);
  await page.getByRole("button", { name: "Create goal" }).click();
  await expect(page).toHaveURL(/\/dashboard\?created=1$/);
}

async function freshContext(browser: Browser) {
  const context = await browser.newContext();
  return { context, page: await context.newPage() };
}

test.describe("authentication and goals", () => {
  test.describe.configure({ mode: "serial" });

  const ada = newLearner("ada");
  const goalTitle = `Learn Kubernetes ${randomUUID().slice(0, 6)}`;

  test("signed-out visitors cannot reach protected pages or the API", async ({ page, request }) => {
    await page.goto("/dashboard");
    await expect(page).toHaveURL(/\/sign-in\?next=%2Fdashboard$/);
    await expect(page.getByRole("heading", { name: "Welcome back" })).toBeVisible();

    // The page redirect is a convenience; the API refuses on its own account.
    const response = await request.get(`${API_URL}/v1/goals`);
    expect(response.status()).toBe(401);
  });

  test("a new user can create an account and lands on their dashboard", async ({ page }) => {
    await signUp(page, ada);

    await expect(page.getByRole("heading", { name: "Your learning goals" })).toBeVisible();
    await expect(page.getByText(`Welcome back, ${ada.name}`)).toBeVisible();
    await expect(page.getByText("You don't have any goals yet")).toBeVisible();
  });

  test("a goal is saved to the account and survives a reload", async ({ page }) => {
    await signIn(page, ada);
    await expect(page).toHaveURL(/\/dashboard$/);

    await createGoal(page, goalTitle);
    await expect(page.getByText("Goal created")).toBeVisible();
    await expect(page.getByText(goalTitle)).toBeVisible();

    await page.goto("/dashboard");
    await expect(page.getByText(goalTitle)).toBeVisible();
    await page.reload();
    await expect(page.getByText(goalTitle)).toBeVisible();
  });

  test("the session lives in HttpOnly cookies, not in script-readable storage", async ({
    page,
  }) => {
    await signIn(page, ada);
    await expect(page).toHaveURL(/\/dashboard$/);

    const storedKeys = await page.evaluate(() => [
      ...Object.keys(localStorage),
      ...Object.keys(sessionStorage),
    ]);
    expect(storedKeys.filter((key) => /auth|token|sb-/i.test(key))).toEqual([]);

    const sessionCookies = (await page.context().cookies()).filter((cookie) =>
      cookie.name.startsWith("sb-"),
    );
    expect(sessionCookies.length).toBeGreaterThan(0);
    // HttpOnly: a script injected into the page cannot read the access or refresh token.
    expect(sessionCookies.every((cookie) => cookie.httpOnly)).toBe(true);
    expect(await page.evaluate(() => document.cookie)).not.toContain("sb-");

    // A second tab in the same browser is signed in too, with no further sign-in.
    const secondTab = await page.context().newPage();
    await secondTab.goto("/dashboard");
    await expect(secondTab.getByRole("heading", { name: "Your learning goals" })).toBeVisible();
    await expect(secondTab.getByText(goalTitle)).toBeVisible();
  });

  test("signing out ends access to protected pages", async ({ page }) => {
    await signIn(page, ada);
    await expect(page).toHaveURL(/\/dashboard$/);

    await page.getByRole("button", { name: "Sign out" }).click();
    await expect(page).toHaveURL(/\/$/);

    await page.goto("/dashboard");
    await expect(page).toHaveURL(/\/sign-in\?next=%2Fdashboard$/);
    await page.goto("/goals/new");
    await expect(page).toHaveURL(/\/sign-in\?next=%2Fgoals%2Fnew$/);
  });

  test("signing back in shows the same goals", async ({ page }) => {
    await signIn(page, ada);

    await expect(page).toHaveURL(/\/dashboard$/);
    await expect(page.getByText(goalTitle)).toBeVisible();
  });

  test("a wrong password gives one generic message and no session", async ({ page }) => {
    await signIn(page, ada, "definitely-not-the-password");

    await expect(page.getByText("The email or password is incorrect.")).toBeVisible();
    await expect(page).toHaveURL(/\/sign-in/);
    await page.goto("/dashboard");
    await expect(page).toHaveURL(/\/sign-in\?next=%2Fdashboard$/);
  });

  test("another user sees none of it", async ({ browser }) => {
    const grace = newLearner("grace");
    const { context, page } = await freshContext(browser);
    try {
      await signUp(page, grace);

      await expect(page.getByText("You don't have any goals yet")).toBeVisible();
      await expect(page.getByText(goalTitle)).toHaveCount(0);
    } finally {
      await context.close();
    }
  });
});
