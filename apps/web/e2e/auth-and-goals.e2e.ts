import { randomUUID } from "node:crypto";

import { expect, test, type Browser, type BrowserContext, type Page } from "@playwright/test";

/**
 * The acceptance scenario, in a real browser against real Supabase Auth and the real API:
 *
 *   sign up → onboarding → a goal on the dashboard → edit → reload and it is still there →
 *   generate a roadmap in the background → it persists, respects the daily minutes and can be
 *   revised into a new version without losing the old one → a lesson is written for a topic,
 *   studied, explained simply, resumed after a reload, finished and re-written as another
 *   version → settings persist →
 *   pause / complete / archive / restore / delete (with confirmations) →
 *   sign out → sign back in → another user can see and change none of it.
 *
 * Roadmaps are produced by the real API and the real worker process; the worker uses the built-in
 * test provider (LLM_PROVIDER=fake), which labels every plan as a sample. No model is called.
 *
 * Nothing here fakes a session: every cookie is set by Supabase through the app. The one place a
 * test reads the session is to prove a *different* account's real token cannot touch these goals.
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
  // A new account starts with the short setup.
  await expect(page).toHaveURL(/\/onboarding$/);
}

/** Submit the sign-in form and return without waiting (for attempts that are meant to fail). */
async function attemptSignIn(page: Page, learner: Learner, password = learner.password) {
  await page.goto("/sign-in");
  await page.getByLabel("Email").fill(learner.email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
}

/** Sign in and wait until the session is really established (the dashboard has loaded). */
async function signIn(page: Page, learner: Learner) {
  await attemptSignIn(page, learner);
  await expect(page).toHaveURL(/\/dashboard$/);
}

async function skipOnboarding(page: Page) {
  await page.getByRole("button", { name: "Skip for now" }).click();
  await expect(page).toHaveURL(/\/dashboard\?notice=skipped$/);
}

async function createGoal(page: Page, title: string, extra?: { targetDate?: string }) {
  await page.goto("/goals/new");
  await page.getByLabel("What do you want to learn?").fill(title);
  if (extra?.targetDate) await page.getByLabel(/Target date/).fill(extra.targetDate);
  await page.getByRole("button", { name: "Create goal" }).click();
  await expect(page).toHaveURL(/\/dashboard\?notice=created$/);
}

async function openGoal(page: Page, title: string) {
  await page.goto("/dashboard");
  await page.getByRole("link", { name: title }).click();
  await expect(page.getByRole("heading", { level: 1, name: title })).toBeVisible();
  return page.url().split("/goals/")[1] ?? "";
}

/** On a goal page with no roadmap: ask for one and wait for the worker to finish it. */
async function generateRoadmap(page: Page) {
  await page.getByRole("button", { name: "Generate roadmap" }).click();
  // The job is queued and a worker runs it; the page follows its progress by itself.
  await expect(page.getByRole("link", { name: /View roadmap/ })).toBeVisible({ timeout: 45_000 });
}

/** The access token of the signed-in browser context, read from Supabase's session cookie. */
async function accessTokenOf(context: BrowserContext): Promise<string> {
  const cookies = (await context.cookies())
    .filter((cookie) => /^sb-.*-auth-token(\.\d+)?$/.test(cookie.name))
    .sort((a, b) => a.name.localeCompare(b.name, "en", { numeric: true }));
  expect(cookies.length).toBeGreaterThan(0);
  const joined = cookies.map((cookie) => cookie.value).join("");
  const json = Buffer.from(joined.replace(/^base64-/, ""), "base64url").toString("utf8");
  return (JSON.parse(json) as { access_token: string }).access_token;
}

async function freshContext(browser: Browser) {
  const context = await browser.newContext();
  return { context, page: await context.newPage() };
}

function bearer(token: string) {
  return { Authorization: `Bearer ${token}` };
}

test.describe("onboarding, goals and the dashboard", () => {
  test.describe.configure({ mode: "serial" });

  const ada = newLearner("ada");
  const firstGoal = `Learn Kubernetes ${randomUUID().slice(0, 6)}`;
  const renamedGoal = `${firstGoal} (renamed)`;
  const secondGoal = `Pass the CKA exam ${randomUUID().slice(0, 6)}`;
  let firstGoalId = "";
  let lessonItemId = "";

  test("signed-out visitors cannot reach protected pages or the API", async ({ page, request }) => {
    for (const path of ["/dashboard", "/onboarding", "/settings", "/goals/new"]) {
      await page.goto(path);
      await expect(page).toHaveURL(new RegExp(`/sign-in\\?next=${encodeURIComponent(path)}$`));
    }
    await expect(page.getByRole("heading", { name: "Welcome back" })).toBeVisible();

    // The page redirects are a convenience; the API refuses on its own account.
    for (const path of ["/v1/me", "/v1/goals", "/v1/goals/summary"]) {
      expect((await request.get(`${API_URL}${path}`)).status()).toBe(401);
    }
  });

  test("a new user is welcomed, answers two questions and creates a first goal without a date", async ({
    page,
  }) => {
    await signUp(page, ada);

    // Step 1: the name from sign-up is already there; only the language question matters.
    await expect(page.getByText("Step 1 of 3")).toBeVisible();
    await expect(page.getByLabel(/What should we call you/)).toHaveValue(ada.name);
    await page.getByRole("button", { name: "Continue" }).click();

    // Step 2: study time and what helps.
    await expect(page).toHaveURL(/step=2$/);
    await expect(page.getByText("Step 2 of 3")).toBeVisible();
    const minutes = page.getByLabel(/How many minutes can you study/);
    await minutes.fill("45");
    await page.getByLabel("Spaced revision").uncheck();
    await page.getByRole("button", { name: "Continue" }).click();

    // Step 3: only a title is needed; the target date is optional and left empty.
    await expect(page).toHaveURL(/step=3$/);
    await expect(page.getByLabel(/Target date/)).toBeEmpty();
    await page.getByLabel("What do you want to learn?").fill(firstGoal);
    await page.getByRole("button", { name: "Create my first goal" }).click();

    await expect(page).toHaveURL(/\/dashboard\?notice=onboarded$/);
    await expect(page.getByText("You're all set")).toBeVisible();
    await expect(page.getByRole("link", { name: firstGoal })).toBeVisible();
    // The study time chosen in step 2 became the goal's own setting.
    await expect(page.getByText("45 minutes a day")).toBeVisible();
  });

  test("the dashboard shows real counts and survives a reload", async ({ page }) => {
    await signIn(page, ada);
    await expect(page).toHaveURL(/\/dashboard$/);

    const glance = page.getByLabel("Your goals at a glance");
    await expect(glance).toContainText("Active");
    await expect(glance.getByText("1", { exact: true }).first()).toBeVisible();
    await expect(page.getByRole("link", { name: firstGoal })).toBeVisible();

    await page.reload();
    await expect(page.getByRole("link", { name: firstGoal })).toBeVisible();
    // Setup is done: the prompt to finish it is gone, and /onboarding no longer redirects.
    await expect(page.getByText("Finish setting up StudyPilot")).toHaveCount(0);
  });

  test("preferences are saved, survive a reload and start the next goal", async ({ page }) => {
    await signIn(page, ada);
    await page.goto("/settings");

    await page.getByLabel("Usual minutes of study per day").fill("75");
    await page.getByLabel(/Hindi/).check();
    await page.getByRole("button", { name: "Save preferences" }).click();
    await expect(page.getByText("Your preferences are saved.")).toBeVisible();

    await page.reload();
    await expect(page.getByLabel("Usual minutes of study per day")).toHaveValue("75");
    await expect(page.getByLabel(/Hindi/)).toBeChecked();

    await page.goto("/goals/new");
    await expect(page.getByLabel("Minutes you can study each day")).toHaveValue("75");
    await expect(page.getByLabel(/Hindi/)).toBeChecked();
    // Unticked in onboarding, and still unticked: the choice was saved, not reset to a default.
    await expect(page.getByLabel("Spaced revision")).not.toBeChecked();
    await expect(page.getByLabel("Worked examples")).toBeChecked();
  });

  test("a second goal can be created with a target date and shows on the dashboard", async ({
    page,
  }) => {
    await signIn(page, ada);
    await createGoal(page, secondGoal, { targetDate: "2030-03-01" });

    await expect(page.getByText("Goal created")).toBeVisible();
    await expect(page.getByRole("link", { name: secondGoal })).toBeVisible();
    await expect(page.getByText("By 1 Mar 2030")).toBeVisible();
    await expect(page.getByText("75 minutes a day")).toBeVisible();
  });

  test("a goal can be edited and the edit is still there after a reload", async ({ page }) => {
    await signIn(page, ada);
    firstGoalId = await openGoal(page, firstGoal);

    await page.getByRole("link", { name: "Edit" }).click();
    await page.getByLabel("What do you want to learn?").fill(renamedGoal);
    await page.getByLabel("Your level today").selectOption("intermediate");
    await page.getByLabel("Minutes you can study each day").fill("30");
    await page.getByRole("button", { name: "Save changes" }).click();

    await expect(page).toHaveURL(new RegExp(`/goals/${firstGoalId}\\?notice=updated$`));
    await expect(page.getByText("Changes saved")).toBeVisible();
    await expect(page.getByRole("heading", { level: 1, name: renamedGoal })).toBeVisible();

    await page.goto("/dashboard");
    await page.reload();
    await expect(page.getByRole("link", { name: renamedGoal })).toBeVisible();
    await expect(page.getByText("Level: Intermediate")).toBeVisible();
    await expect(page.getByText("30 minutes a day")).toBeVisible();
  });

  test("invalid edits show the problem next to the field and change nothing", async ({ page }) => {
    await signIn(page, ada);
    await page.goto(`/goals/${firstGoalId}/edit`);

    await page.getByLabel("Minutes you can study each day").fill("5");
    await page.getByLabel("Minutes you can study each day").evaluate((input) => {
      (input as HTMLInputElement).removeAttribute("min"); // get past the browser's own check
    });
    await page.getByRole("button", { name: "Save changes" }).click();

    await expect(page.getByText(/at least 10 minutes/)).toBeVisible();
    await page.goto(`/goals/${firstGoalId}`);
    await expect(page.getByText("30 minutes")).toBeVisible();
  });

  test("a roadmap is generated in the background and is still there after a reload", async ({
    page,
  }) => {
    await signIn(page, ada);
    await page.goto(`/goals/${firstGoalId}`);
    await expect(page.getByText("Turn this goal into a study plan")).toBeVisible();

    await generateRoadmap(page);
    await expect(page.getByText("Version 1 of 1")).toBeVisible();

    await page.getByRole("link", { name: /View roadmap/ }).click();
    await expect(page).toHaveURL(new RegExp(`/goals/${firstGoalId}/roadmap$`));
    await expect(page.getByRole("heading", { level: 1 })).toContainText(renamedGoal);
    await expect(
      page.getByText("This roadmap came from the built-in test provider, not an AI model."),
    ).toBeVisible();
    await expect(page.getByRole("heading", { name: "Modules and topics" })).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "By the end you will be able to" }),
    ).toBeVisible();
    await expect(page.getByText(/not an official syllabus/)).toBeVisible();

    // Reopening the app later: the plan comes back from the database.
    await page.reload();
    await expect(page.getByRole("heading", { level: 1 })).toContainText(renamedGoal);
    await expect(page.getByRole("heading", { name: "Modules and topics" })).toBeVisible();
    await page.goto(`/goals/${firstGoalId}`);
    await expect(page.getByText("Version 1 of 1")).toBeVisible();
  });

  test("the stored schedule never asks for more than the daily minutes", async ({ page }) => {
    await signIn(page, ada);
    await page.goto(`/goals/${firstGoalId}/roadmap`);

    await page.getByText(/Day-by-day schedule/).click();
    const days = await page.locator("details ol > li > p").allInnerTexts();

    expect(days.length).toBeGreaterThan(0);
    for (const day of days) {
      const minutes = /(\d+) min/.exec(day);
      expect(minutes, `"${day}" should be a number of minutes under an hour`).not.toBeNull();
      expect(Number(minutes?.[1])).toBeLessThanOrEqual(30); // the goal was edited to 30 a day
    }
  });

  test("a revision adds version 2, keeps version 1, and either can be made current", async ({
    page,
  }) => {
    await signIn(page, ada);
    await page.goto(`/goals/${firstGoalId}/roadmap`);

    await page.getByRole("button", { name: "Revise or regenerate" }).click();
    const dialog = page.getByRole("dialog", { name: "Make a new version" });
    await expect(dialog.getByText(/every earlier version stay available/)).toBeVisible();
    await dialog.getByLabel(/What should change/).fill("Fewer topics, more practice");
    await dialog.getByRole("button", { name: "Create new version" }).click();

    await expect(page).toHaveURL(new RegExp(`/goals/${firstGoalId}$`));
    await expect(page.getByText("Version 2 of 2")).toBeVisible({ timeout: 45_000 });

    await page.getByRole("link", { name: /View roadmap/ }).click();
    const versions = page.getByRole("region", { name: "Versions" });
    await expect(versions.getByText(/Asked for: “Fewer topics, more practice”/)).toBeVisible();

    // Version 1 is still there, unchanged, and can be made current again.
    await versions.getByRole("link", { name: "Version 1" }).click();
    await expect(page).toHaveURL(/\?version=1$/);
    await expect(page.getByText("Earlier version", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Make this version current" }).click();

    await expect(page).toHaveURL(/\/roadmap\?notice=version-switched$/);
    await expect(page.getByText("Nothing was deleted: every version is kept.")).toBeVisible();
    await expect(
      page.getByRole("region", { name: "Versions" }).getByRole("link", { name: "Version 2" }),
    ).toBeVisible();
  });

  test("an unknown roadmap version is simply not found", async ({ page }) => {
    await signIn(page, ada);

    await page.goto(`/goals/${firstGoalId}/roadmap?version=99`);

    await expect(page.getByText("We couldn't find that")).toBeVisible();
  });

  test("a lesson is written in the background, studied, and is still there after a reload", async ({
    page,
  }) => {
    await signIn(page, ada);
    await page.goto(`/goals/${firstGoalId}/roadmap`);
    await expect(page.getByRole("heading", { name: "Your progress" })).toBeVisible();
    await expect(page.getByText(/0 of \d+ topics finished/)).toBeVisible();

    await page.getByRole("link", { name: /^Start studying:/ }).click();
    await expect(page).toHaveURL(new RegExp(`/goals/${firstGoalId}/learn/[0-9a-f-]{36}$`));
    lessonItemId = page.url().split("/learn/")[1] ?? "";
    await expect(page.getByText("This topic doesn't have a lesson yet")).toBeVisible();

    // The lesson is written by the worker; the page follows its progress by itself.
    await page.getByRole("button", { name: "Write this lesson" }).click();
    await expect(page.getByRole("button", { name: "Explain simply" })).toBeVisible({
      timeout: 45_000,
    });

    await expect(page.getByRole("heading", { name: "What you will learn" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Key terms" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Worked examples" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Summary" })).toBeVisible();
    await expect(page.getByText("Sample lesson", { exact: true })).toBeVisible();
    await expect(page.getByText(/written from general knowledge/)).toBeVisible();

    await page.reload();
    await expect(page.getByRole("button", { name: "Explain simply" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "What you will learn" })).toBeVisible();
  });

  test("Explain simply shows the lesson's own simple explanation and hides it again", async ({
    page,
  }) => {
    await signIn(page, ada);
    await page.goto(`/goals/${firstGoalId}/learn/${lessonItemId}`);
    await expect(page.getByRole("heading", { name: "In simple words" })).toHaveCount(0);

    await page.getByRole("button", { name: "Explain simply" }).click();
    await expect(page.getByRole("heading", { name: "In simple words" })).toBeVisible();
    await expect(page.getByText(/picture frame with nothing in it yet/)).toBeVisible();

    await page.getByRole("button", { name: "Hide the simple explanation" }).click();
    await expect(page.getByRole("heading", { name: "In simple words" })).toHaveCount(0);
  });

  test("progress is saved and the lesson picks up where the learner left off", async ({ page }) => {
    await signIn(page, ada);
    await page.goto(`/goals/${firstGoalId}/learn/${lessonItemId}`);
    const token = await accessTokenOf(page.context());
    const study = async () => {
      const response = await page.request.get(`${API_URL}/v1/roadmap-items/${lessonItemId}/study`, {
        headers: bearer(token),
      });
      return (await response.json()) as {
        lesson: { id: string; content: { sections: { id: string }[] } };
        progress: { completed_section_ids: string[]; current_section_id: string | null } | null;
      };
    };
    const sections = (await study()).lesson.content.sections.map((section) => section.id);
    expect(sections.length).toBeGreaterThan(2);

    // Tick the first section...
    await page
      .getByRole("button", { name: /Mark section as done for/ })
      .first()
      .click();
    await expect(page.getByTestId("save-status")).toHaveText("Progress saved");
    await expect(page.getByText(`1 of ${sections.length} sections done`).first()).toBeVisible();

    // ...and read on to the end: the reader's position is saved too.
    await page.keyboard.press("End");
    await expect
      .poll(async () => (await study()).progress?.current_section_id, { timeout: 15_000 })
      .toBe(sections.at(-1));

    // Reopen the lesson later: the progress is back, and the page offers to continue.
    await page.goto(`/goals/${firstGoalId}/learn/${lessonItemId}`);
    await expect(page.getByText("Welcome back")).toBeVisible();
    await expect(page.getByText(/You left off at/)).toBeVisible();
    await expect(page.getByText(`1 of ${sections.length} sections done`).first()).toBeVisible();

    await page.getByRole("button", { name: "Start from the top" }).click();
    await expect(page.getByText("Welcome back")).toHaveCount(0);

    // The roadmap shows the topic as in progress.
    await page.goto(`/goals/${firstGoalId}/roadmap`);
    await expect(page.getByRole("link", { name: /^Continue studying:/ })).toBeVisible();
    await expect(page.getByText(`1 of ${sections.length} sections`).first()).toBeVisible();
  });

  test("finishing a lesson marks the topic done on the roadmap and the goal", async ({ page }) => {
    await signIn(page, ada);
    await page.goto(`/goals/${firstGoalId}/learn/${lessonItemId}`);

    await page.getByRole("button", { name: "Finish lesson" }).click();
    await expect(page.getByRole("heading", { name: "Lesson complete" })).toBeVisible();
    await expect(page.getByTestId("save-status")).toHaveText("Progress saved");
    await expect(page.getByRole("link", { name: /^Next topic:/ })).toBeVisible();

    await page.goto(`/goals/${firstGoalId}/roadmap`);
    await expect(page.getByText(/^1 of \d+ topics finished$/)).toBeVisible();
    await expect(page.getByRole("link", { name: /^Review/ }).first()).toBeVisible();

    await page.goto(`/goals/${firstGoalId}`);
    await expect(page.getByText(/^1 of \d+ topics finished$/)).toBeVisible();
    await expect(page.getByRole("link", { name: "Continue studying" })).toBeVisible();
  });

  test("the next and previous topic are one click away, and the contents list them all", async ({
    page,
  }) => {
    await signIn(page, ada);
    await page.goto(`/goals/${firstGoalId}/learn/${lessonItemId}`);

    const contents = page.getByRole("complementary", { name: "Contents" });
    await expect(contents.getByRole("navigation", { name: "In this lesson" })).toBeVisible();
    const topics = contents.getByRole("navigation", { name: "Roadmap topics" });
    await expect(topics.getByRole("link").first()).toHaveAttribute("aria-current", "page");
    await expect(topics.getByText("Done").first()).toBeVisible();

    await page
      .getByRole("navigation", { name: "Topic navigation" })
      .getByText("Next topic")
      .click();
    await expect(page.getByText("This topic doesn't have a lesson yet")).toBeVisible();
    await expect(page).not.toHaveURL(new RegExp(`/learn/${lessonItemId}$`));

    await page
      .getByRole("navigation", { name: "Topic navigation" })
      .getByText("Previous topic")
      .click();
    await expect(page).toHaveURL(new RegExp(`/learn/${lessonItemId}$`));
  });

  test("another version can be asked for: the first is kept, each has its own progress", async ({
    page,
  }) => {
    await signIn(page, ada);
    await page.goto(`/goals/${firstGoalId}/learn/${lessonItemId}`);

    await page.getByRole("button", { name: "Write another version" }).click();
    const dialog = page.getByRole("dialog", { name: "Write another version of this lesson" });
    await dialog.getByRole("radio", { name: /Simpler/ }).check();
    await dialog.getByLabel(/Anything else/).fill("Use cooking as the example");
    await dialog.getByRole("button", { name: "Write the new version" }).click();

    await expect(page).toHaveURL(new RegExp(`/goals/${firstGoalId}/learn/${lessonItemId}$`));
    const versions = page.getByRole("region", { name: "Versions of this lesson" });
    await expect(versions.getByText("Version 2 (reading)")).toBeVisible({ timeout: 45_000 });
    await expect(page.getByText("This version was asked to use simpler words.")).toBeVisible();
    await expect(page.getByText("0 of 4 sections done").first()).toBeVisible(); // a fresh version

    // The first version is untouched, and still finished.
    await versions.getByRole("link", { name: "Version 1" }).click();
    await expect(page).toHaveURL(/\?lesson=/);
    await expect(page.getByText("Earlier version", { exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Lesson complete" })).toBeVisible();
  });

  test("a goal can be paused, resumed, completed and reopened", async ({ page }) => {
    await signIn(page, ada);
    await page.goto(`/goals/${firstGoalId}`);

    await page.getByRole("button", { name: "Pause" }).click();
    await expect(page.getByText("Goal paused")).toBeVisible();
    await expect(page.getByText("Paused", { exact: true })).toBeVisible();

    await page.getByRole("button", { name: "Resume" }).click();
    await expect(page.getByText("This goal is active again")).toBeVisible();

    await page.getByRole("button", { name: "Mark complete" }).click();
    await expect(page.getByText("Goal completed")).toBeVisible();
    await expect(page.getByText("Completed", { exact: true })).toBeVisible();

    await page.goto("/dashboard");
    await expect(page.getByRole("heading", { name: "Completed" })).toBeVisible();
    await expect(page.getByRole("link", { name: renamedGoal })).toBeVisible();

    await page.goto(`/goals/${firstGoalId}`);
    await page.getByRole("button", { name: "Reopen" }).click();
    await expect(page.getByText("This goal is active again")).toBeVisible();
  });

  test("archiving asks first, can be cancelled, and the goal can be restored", async ({ page }) => {
    await signIn(page, ada);
    await page.goto(`/goals/${firstGoalId}`);

    // Cancel: nothing happens.
    await page.getByRole("button", { name: "Archive" }).click();
    const dialog = page.getByRole("dialog", { name: "Archive this goal?" });
    await expect(dialog).toBeVisible();
    await dialog.getByRole("button", { name: "Cancel" }).click();
    await expect(dialog).toBeHidden();
    await expect(page.getByText("Active", { exact: true })).toBeVisible();

    // Confirm: the goal leaves the dashboard but is in the archive.
    await page.getByRole("button", { name: "Archive" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Archive goal" }).click();
    await expect(page).toHaveURL(/\/dashboard\?notice=archived$/);
    await expect(page.getByText("Goal archived")).toBeVisible();
    await expect(page.getByRole("link", { name: renamedGoal })).toHaveCount(0);

    await page.getByRole("link", { name: "View archive" }).click();
    await expect(page.getByRole("link", { name: renamedGoal })).toBeVisible();

    // Archived goals are read-only until restored.
    await page.getByRole("link", { name: renamedGoal }).click();
    await expect(page.getByText(/read-only/)).toBeVisible();
    await expect(page.getByRole("link", { name: "Edit" })).toHaveCount(0);
    await page.goto(`/goals/${firstGoalId}/edit`);
    await expect(page).toHaveURL(new RegExp(`/goals/${firstGoalId}$`)); // sent back, not editable

    await page.getByRole("button", { name: "Restore" }).click();
    await expect(page.getByText("This goal is active again")).toBeVisible();
    await expect(page.getByRole("link", { name: "Edit" })).toBeVisible();
  });

  test("an archived goal's roadmap can be read but not changed", async ({ page }) => {
    await signIn(page, ada);
    await page.goto(`/goals/${firstGoalId}`);
    await page.getByRole("button", { name: "Archive" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Archive goal" }).click();
    await expect(page).toHaveURL(/\/dashboard\?notice=archived$/);

    await page.goto(`/goals/${firstGoalId}`);
    await expect(page.getByRole("link", { name: /View roadmap/ })).toBeVisible();
    await expect(page.getByRole("button", { name: "Revise or regenerate" })).toHaveCount(0);

    await page.goto(`/goals/${firstGoalId}/roadmap`);
    await expect(page.getByText(/its roadmap is read-only/)).toBeVisible();
    await expect(page.getByRole("button", { name: "Revise or regenerate" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Make current" })).toHaveCount(0);

    // Lessons stay readable, and nothing in them can be changed.
    await page.goto(`/goals/${firstGoalId}/learn/${lessonItemId}`);
    await expect(page.getByText(/its lessons are read-only/).first()).toBeVisible();
    await expect(page.getByRole("button", { name: "Explain simply" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Write another version" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /Mark section as done/ })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Finish lesson" })).toHaveCount(0);

    await page.goto(`/goals/${firstGoalId}`);
    await page.getByRole("button", { name: "Restore" }).click();
    await expect(page.getByText("This goal is active again")).toBeVisible();
    await expect(page.getByRole("button", { name: "Revise or regenerate" })).toBeVisible();
  });

  test("only an archived goal can be deleted, after a warning, and then it is gone", async ({
    page,
  }) => {
    await signIn(page, ada);
    await page.goto(`/goals/${firstGoalId}`);
    await expect(page.getByRole("button", { name: "Delete permanently" })).toHaveCount(0);

    await page.getByRole("button", { name: "Archive" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Archive goal" }).click();
    await expect(page).toHaveURL(/\/dashboard\?notice=archived$/);

    await page.goto(`/goals/${firstGoalId}`);
    await page.getByRole("button", { name: "Delete permanently" }).click();
    const dialog = page.getByRole("dialog", { name: "Delete this goal permanently?" });
    await expect(dialog.getByText(/cannot be undone/)).toBeVisible();
    await dialog.getByRole("button", { name: "Delete forever" }).click();

    await expect(page).toHaveURL(/\/goals\/archived\?notice=deleted$/);
    await expect(page.getByText("Goal deleted permanently")).toBeVisible();
    await expect(page.getByRole("link", { name: renamedGoal })).toHaveCount(0);

    await page.goto(`/goals/${firstGoalId}`);
    await expect(page.getByText("We couldn't find that")).toBeVisible();
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
    await expect(secondTab.getByRole("link", { name: secondGoal })).toBeVisible();
  });

  test("signing out ends access, and signing back in restores everything", async ({ page }) => {
    await signIn(page, ada);
    await page.getByRole("button", { name: "Sign out" }).click();
    await expect(page).toHaveURL(/\/$/);

    await page.goto("/dashboard");
    await expect(page).toHaveURL(/\/sign-in\?next=%2Fdashboard$/);
    await page.goto("/settings");
    await expect(page).toHaveURL(/\/sign-in\?next=%2Fsettings$/);

    await signIn(page, ada);
    await expect(page).toHaveURL(/\/dashboard$/);
    await expect(page.getByRole("link", { name: secondGoal })).toBeVisible();
  });

  test("a wrong password gives one generic message and no session", async ({ page }) => {
    await attemptSignIn(page, ada, "definitely-not-the-password");

    await expect(page.getByText("The email or password is incorrect.")).toBeVisible();
    await expect(page).toHaveURL(/\/sign-in/);
    await page.goto("/dashboard");
    await expect(page).toHaveURL(/\/sign-in\?next=%2Fdashboard$/);
  });

  test.describe("another user", () => {
    const grace = newLearner("grace");
    let adasGoalId = "";
    let adasRoadmapId = "";
    let adasJobId = "";
    let adasItemId = "";
    let adasLessonId = "";

    test("sees none of Ada's goals and starts from a clean slate", async ({ browser, page }) => {
      await signIn(page, ada);
      adasGoalId = await openGoal(page, secondGoal);
      await generateRoadmap(page); // her second goal has a target date, so the plan must fit it
      const adasToken = await accessTokenOf(page.context());
      const roadmaps = await page.request.get(`${API_URL}/v1/goals/${adasGoalId}/roadmaps`, {
        headers: bearer(adasToken),
      });
      adasRoadmapId = (await roadmaps.json()).current_id;
      const jobs = await page.request.get(`${API_URL}/v1/goals/${adasGoalId}/jobs`, {
        headers: bearer(adasToken),
      });
      adasJobId = (await jobs.json()).items[0].id;
      expect(adasRoadmapId).toBeTruthy();

      // She has a written lesson too, for the next tests to try to reach.
      await page.goto(`/goals/${adasGoalId}/roadmap`);
      await page.getByRole("link", { name: /^Start studying:/ }).click();
      await expect(page).toHaveURL(new RegExp(`/goals/${adasGoalId}/learn/[0-9a-f-]{36}$`));
      adasItemId = page.url().split("/learn/")[1] ?? "";
      await page.getByRole("button", { name: "Write this lesson" }).click();
      await expect(page.getByRole("button", { name: "Explain simply" })).toBeVisible({
        timeout: 45_000,
      });
      const study = await page.request.get(`${API_URL}/v1/roadmap-items/${adasItemId}/study`, {
        headers: bearer(adasToken),
      });
      adasLessonId = (await study.json()).lesson.id;
      expect(adasLessonId).toBeTruthy();

      const other = await freshContext(browser);
      try {
        await signUp(other.page, grace);
        await skipOnboarding(other.page);

        await expect(other.page.getByText("You don't have any goals yet")).toBeVisible();
        await expect(other.page.getByRole("link", { name: secondGoal })).toHaveCount(0);

        // Ada's goal address looks exactly like an address that doesn't exist.
        await other.page.goto(`/goals/${adasGoalId}`);
        await expect(other.page.getByText("We couldn't find that")).toBeVisible();
        await other.page.goto(`/goals/${adasGoalId}/edit`);
        await expect(other.page.getByText("We couldn't find that")).toBeVisible();
        await other.page.goto(`/goals/${adasGoalId}/roadmap`);
        await expect(other.page.getByText("We couldn't find that")).toBeVisible();
      } finally {
        await other.context.close();
      }
    });

    test("cannot read, change, move or delete Ada's goal even with a real token", async ({
      browser,
      request,
    }) => {
      const other = await freshContext(browser);
      try {
        // Grace already has an account from the previous test: sign in as her.
        await signIn(other.page, grace);
        const token = await accessTokenOf(other.context);

        const goalUrl = `${API_URL}/v1/goals/${adasGoalId}`;
        const read = await request.get(goalUrl, { headers: bearer(token) });
        const edit = await request.patch(goalUrl, {
          headers: bearer(token),
          data: { title: "Hijacked" },
        });
        const move = await request.put(`${goalUrl}/status`, {
          headers: bearer(token),
          data: { status: "archived" },
        });
        const remove = await request.delete(goalUrl, { headers: bearer(token) });
        const mine = await request.get(`${API_URL}/v1/goals`, { headers: bearer(token) });

        expect([read.status(), edit.status(), move.status(), remove.status()]).toEqual([
          404, 404, 404, 404,
        ]);

        // The same goes for the roadmap and the job behind it.
        const roadmapUrl = `${API_URL}/v1/roadmaps/${adasRoadmapId}`;
        const attempts = [
          await request.get(roadmapUrl, { headers: bearer(token) }),
          await request.post(`${roadmapUrl}/make-current`, { headers: bearer(token) }),
          await request.get(`${API_URL}/v1/jobs/${adasJobId}`, { headers: bearer(token) }),
          await request.post(`${API_URL}/v1/jobs/${adasJobId}/cancel`, { headers: bearer(token) }),
          await request.get(`${goalUrl}/roadmaps`, { headers: bearer(token) }),
          await request.post(`${goalUrl}/roadmaps`, { headers: bearer(token), data: {} }),
        ];
        expect(attempts.map((response) => response.status())).toEqual([
          404, 404, 404, 404, 404, 404,
        ]);
        expect((await mine.json()).items).toEqual([]);
      } finally {
        await other.context.close();
      }
    });

    test("cannot read, start or save progress in Ada's lessons even with a real token", async ({
      browser,
      request,
    }) => {
      const other = await freshContext(browser);
      try {
        await signIn(other.page, grace);
        const token = await accessTokenOf(other.context);

        const attempts = [
          await request.get(`${API_URL}/v1/roadmap-items/${adasItemId}/study`, {
            headers: bearer(token),
          }),
          await request.get(`${API_URL}/v1/roadmap-items/${adasItemId}/study`, {
            headers: bearer(token),
            params: { lesson_id: adasLessonId },
          }),
          await request.post(`${API_URL}/v1/roadmap-items/${adasItemId}/lessons`, {
            headers: bearer(token),
            data: { regenerate: true },
          }),
          await request.put(`${API_URL}/v1/lessons/${adasLessonId}/progress`, {
            headers: bearer(token),
            data: { completed: true },
          }),
        ];
        expect(attempts.map((response) => response.status())).toEqual([404, 404, 404, 404]);

        // Her page for Ada's topic looks exactly like a page that doesn't exist.
        await other.page.goto(`/goals/${adasGoalId}/learn/${adasItemId}`);
        await expect(other.page.getByText("We couldn't find that")).toBeVisible();
      } finally {
        await other.context.close();
      }
    });

    test("and Ada's goal is untouched afterwards", async ({ page }) => {
      await signIn(page, ada);

      await page.goto(`/goals/${adasGoalId}`);
      await expect(page.getByRole("heading", { level: 1, name: secondGoal })).toBeVisible();
      await expect(page.getByText("Active", { exact: true })).toBeVisible();
      await expect(page.getByText("Version 1 of 1")).toBeVisible(); // and so is her roadmap

      await page.goto(`/goals/${adasGoalId}/learn/${adasItemId}`); // and her lesson
      await expect(page.getByRole("button", { name: "Explain simply" })).toBeVisible();
    });
  });
});
