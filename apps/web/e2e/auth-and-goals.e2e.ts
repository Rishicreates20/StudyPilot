import { randomUUID } from "node:crypto";

import {
  expect,
  test,
  type Browser,
  type BrowserContext,
  type Locator,
  type Page,
} from "@playwright/test";

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

/**
 * The right answers to the built-in test provider's sample questions
 * (services/api/app/ai/fake_quiz.py). The real answer key is never readable from a browser, which
 * is the point of these tests; but this provider asks a fixed set of questions, so a test can
 * answer them properly.
 */
const RIGHT_OPTION: Readonly<Record<string, string>> = {
  "Which habit helps most when you want to remember a new idea for a long time?":
    "Reviewing it again after a few days",
  "What is a good first step when a problem looks too big to start?":
    "Splitting it into smaller parts",
  "Why is explaining an idea aloud useful for learning?":
    "It shows which parts you cannot yet explain",
  "Which study session is usually most effective for focus?": "A short block with one clear goal",
  "What should you do after getting a practice question wrong?":
    "Find out why the answer was wrong",
  "How does testing yourself differ from rereading?": "It makes you pull the answer from memory",
  "Which note is the most helpful to write down?": "A question you could not answer",
  "When is a break most useful during hard study?": "When your attention starts to drift",
  "What does spacing your practice over several days do?": "It makes what you learn last longer",
  "What is the best use of a worked example?": "Study each step, then try a similar one yourself",
};
const TRUE_STATEMENTS: ReadonlySet<string> = new Set([
  "Making mistakes while practising is a normal and useful part of learning.",
  "Mixing different kinds of problems in one session can improve your understanding.",
  "Writing a short summary in your own words can show gaps in your understanding.",
]);
const MODEL_ANSWER: Readonly<Record<string, string>> = {
  "In two or three sentences, explain how you would use a short quiz to plan what to study next.":
    "A quiz shows which questions I got wrong. I would spend my next session on those weak parts, and check them again afterwards to see if I improved.",
  "In two or three sentences, describe why spreading study over several days helps memory.":
    "Memory fades if I do not revisit an idea. Reviewing it again strengthens what I remember, for example by going over my notes a few days later.",
  "In two or three sentences, say what you would do after finding a gap in your understanding.":
    "I would go back to the lesson, write down what was unclear, and then try a similar question to practise it again.",
  "In two or three sentences, explain why explaining an idea aloud can help you learn.":
    "Explaining aloud shows me what I cannot yet explain. It makes me organise the idea, and then I can fix the gaps I noticed.",
};

/**
 * Press a button until its effect shows. A click that lands before the page has hydrated is lost,
 * and the button is on the page well before that, so a test presses it again rather than guessing
 * how long hydration takes. Pressing twice is harmless here: starting a quiz that is already being
 * written is refused by the API.
 */
async function pressUntil(button: Locator, effect: Locator, timeout = 30_000) {
  await expect(async () => {
    if (!(await effect.first().isVisible())) await button.click({ timeout: 2_000 });
    await expect(effect.first()).toBeVisible({ timeout: 4_000 });
  }).toPass({ timeout });
}

/** On a quiz page: answer every question correctly (the short answer in the model answer's words). */
async function answerQuizCorrectly(page: Page) {
  const groups = page.getByRole("group");
  await expect(groups.first()).toBeVisible(); // the quiz page has loaded
  const count = await groups.count();
  expect(count).toBeGreaterThan(2);
  for (let index = 0; index < count; index += 1) {
    const group = groups.nth(index);
    const label = await group.evaluate((element) => {
      const id = element.getAttribute("aria-labelledby");
      return (id ? document.getElementById(id)?.textContent : null) ?? "";
    });
    // "3.Which habit…" -> the prompt, without its number or the sample set marker.
    const prompt =
      label
        .replace(/^\d+\./, "")
        .split(" (built-in test question set")[0]
        ?.trim() ?? "";
    if (await group.getByRole("textbox").count()) {
      const model = MODEL_ANSWER[prompt];
      if (!model) throw new Error(`No sample answer known for: ${prompt}`);
      await group.getByRole("textbox").fill(model);
    } else if (prompt in RIGHT_OPTION) {
      await group.getByRole("radio", { name: RIGHT_OPTION[prompt] ?? "", exact: true }).check();
    } else if (await group.getByRole("radio", { name: "True", exact: true }).count()) {
      const name = TRUE_STATEMENTS.has(prompt) ? "True" : "False";
      await group.getByRole("radio", { name, exact: true }).check();
    } else {
      throw new Error(`No sample answer known for: ${prompt}`);
    }
  }
}

async function freshContext(browser: Browser) {
  const context = await browser.newContext();
  return { context, page: await context.newPage() };
}

function bearer(token: string) {
  return { Authorization: `Bearer ${token}` };
}

/** A 1x1 PNG: any real picture would do, since the test provider "reads" whatever it is given. */
const TINY_PNG =
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==";

type RoadmapTopic = { id: string; title: string; description: string };

/** A topic of the goal's current roadmap that has no lesson yet, found through the API. */
async function topicWithoutLesson(
  page: Page,
  token: string,
  goalId: string,
): Promise<RoadmapTopic> {
  const roadmaps = await page.request.get(`${API_URL}/v1/goals/${goalId}/roadmaps`, {
    headers: bearer(token),
  });
  const currentId = (await roadmaps.json()).current_id as string;
  const roadmap = await page.request.get(`${API_URL}/v1/roadmaps/${currentId}`, {
    headers: bearer(token),
  });
  const modules = (await roadmap.json()).modules as {
    topics: { id: string; title: string; description: string; study: { has_lesson: boolean } }[];
  }[];
  const topic = modules.flatMap((module) => module.topics).find((t) => !t.study.has_lesson);
  expect(topic, "the roadmap should have a topic without a lesson").toBeTruthy();
  return { id: topic!.id, title: topic!.title, description: topic!.description };
}

/** Study material that shares its words with the topic, so it is the passage a search finds. */
function textAbout(topic: RoadmapTopic): string {
  return (
    `${topic.title}. ${topic.description}\n\n` +
    "In this course the key rule is that every value has exactly one owner, " +
    "and moving a value transfers that ownership."
  );
}

test.describe("onboarding, goals and the dashboard", () => {
  test.describe.configure({ mode: "serial" });

  const ada = newLearner("ada");
  const firstGoal = `Learn Kubernetes ${randomUUID().slice(0, 6)}`;
  const renamedGoal = `${firstGoal} (renamed)`;
  const secondGoal = `Pass the CKA exam ${randomUUID().slice(0, 6)}`;
  let firstGoalId = "";
  let lessonItemId = "";
  let quizId = "";
  let attemptId = "";
  let practiceQuizId = "";
  let thirdAttemptUrl = "";
  let documentTopic: RoadmapTopic = { id: "", title: "", description: "" };
  let documentText = "";
  let textDocumentId = "";
  let imageDocumentId = "";

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

    // The button is on the page before the reader has hydrated, and a click before that is lost:
    // press it again until the lesson reports it is complete.
    const complete = page.getByRole("heading", { name: "Lesson complete" });
    await expect(async () => {
      if (!(await complete.isVisible())) {
        await page.getByRole("button", { name: "Finish lesson" }).click({ timeout: 2_000 });
      }
      await expect(complete).toBeVisible({ timeout: 3_000 });
    }).toPass({ timeout: 25_000 });
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

  test("a quiz is written from the lesson, and nothing about its answers is readable before it is submitted", async ({
    page,
  }) => {
    await signIn(page, ada);
    await page.goto(`/goals/${firstGoalId}/learn/${lessonItemId}`);
    await expect(page.getByRole("heading", { name: /Check what you.ve learned/ })).toBeVisible();

    // The quiz is written by the worker; the page follows its progress by itself.
    await pressUntil(
      page.getByRole("button", { name: "Take a quiz" }),
      page.getByText("Writing your quiz").or(page.getByRole("link", { name: "Take the quiz" })),
    );
    await expect(page.getByRole("link", { name: "Take the quiz" })).toBeVisible({
      timeout: 45_000,
    });
    await page.reload();
    await expect(page.getByText("Your quiz is ready")).toBeVisible();

    await page.getByRole("link", { name: "Take the quiz" }).click();
    await expect(page).toHaveURL(
      new RegExp(`/goals/${firstGoalId}/learn/${lessonItemId}/quiz/[0-9a-f-]{36}$`),
    );
    quizId = page.url().split("/quiz/")[1] ?? "";
    await expect(page.getByText("Sample quiz", { exact: true }).first()).toBeVisible();
    await expect(page.getByRole("group")).toHaveCount(5);
    await expect(page.getByText("0 of 5 answered")).toBeVisible();

    // Nothing on the page says what is right or why.
    const text = await page.locator("main").innerText();
    expect(text).not.toMatch(/correct answer|as most study guidance agrees|model answer/i);

    // Nor does the API: the quiz carries questions and options only.
    const token = await accessTokenOf(page.context());
    const response = await page.request.get(`${API_URL}/v1/quizzes/${quizId}`, {
      headers: bearer(token),
    });
    expect(response.status()).toBe(200);
    expect(await response.text()).not.toMatch(
      /correct_option|explanation|rubric|model_answer|option_notes|is_correct/,
    );
  });

  test("answering nothing scores zero: the topic needs practice, and the next step is a small one", async ({
    page,
  }) => {
    await signIn(page, ada);
    await page.goto(`/goals/${firstGoalId}/learn/${lessonItemId}/quiz/${quizId}`);

    await page.getByRole("button", { name: "Submit answers" }).click();
    await expect(page).toHaveURL(
      new RegExp(`/goals/${firstGoalId}/learn/${lessonItemId}/results/[0-9a-f-]{36}$`),
    );
    attemptId = page.url().split("/results/")[1] ?? "";

    await expect(page.getByRole("heading", { level: 1, name: /^Results:/ })).toBeVisible();
    await expect(page.getByText("0%").first()).toBeVisible();
    await expect(page.getByText("Not answered")).toHaveCount(5);
    // Every question explains itself, and the right answers are shown now.
    await expect(page.getByText("Why", { exact: true })).toHaveCount(5);
    await expect(page.getByText("Correct answer").first()).toBeVisible();

    // The topic is weak, and the recommendation is a practice quiz, not starting the course again.
    await expect(page.getByText("Needs practice").first()).toBeVisible();
    await expect(page.getByText("Your next step")).toBeVisible();
    await expect(page.getByText(/You scored 0% on/)).toBeVisible();
    await expect(page.getByRole("button", { name: "Practise these parts" })).toBeVisible();
    await expect(page.getByText(/don.t need to repeat the rest of the course/)).toBeVisible();
    await expect(page.getByText(/· weak/).first()).toBeVisible();

    // The results are stored: they are still there after a reload.
    await page.reload();
    await expect(page.getByText("Not answered")).toHaveCount(5);
    await expect(page.getByText(/You scored 0% on/)).toBeVisible();
  });

  test("a quiz can be submitted once: its page points to the results and the API refuses a second try", async ({
    page,
  }) => {
    await signIn(page, ada);
    await page.goto(`/goals/${firstGoalId}/learn/${lessonItemId}/quiz/${quizId}`);

    await expect(page.getByText("You have already submitted this quiz")).toBeVisible();
    await expect(page.getByRole("button", { name: "Submit answers" })).toHaveCount(0);
    await page.getByRole("link", { name: "See your results" }).click();
    await expect(page).toHaveURL(new RegExp(`/results/${attemptId}$`));

    const token = await accessTokenOf(page.context());
    const again = await page.request.post(`${API_URL}/v1/quizzes/${quizId}/attempts`, {
      headers: bearer(token),
      data: { answers: [] },
    });
    expect(again.status()).toBe(409);
    expect((await again.json()).code).toBe("QUIZ_ALREADY_SUBMITTED");
  });

  test("weak topics show on the topic page, the goal page and the dashboard", async ({ page }) => {
    await signIn(page, ada);

    await page.goto(`/goals/${firstGoalId}/learn/${lessonItemId}`);
    await expect(page.getByText("How well you know this topic")).toBeVisible();
    await expect(page.getByText("Needs practice").first()).toBeVisible();

    await page.goto(`/goals/${firstGoalId}`);
    await expect(page.getByRole("heading", { name: "Your mastery" })).toBeVisible();
    const topics = page.getByRole("list", { name: "Progress by topic" });
    await expect(topics.getByText("Needs practice").first()).toBeVisible();
    await expect(topics.getByText("Not assessed yet").first()).toBeVisible();
    await expect(page.getByRole("button", { name: "Practise these parts" })).toBeVisible();

    await page.goto("/dashboard");
    await expect(page.getByRole("heading", { name: "Where you stand" })).toBeVisible();
    await expect(page.getByText("Weakest topics")).toBeVisible();
    await expect(page.getByRole("button", { name: "Practise these parts" })).toBeVisible();
  });

  test("a practice quiz asks new questions; good answers raise the score without erasing the weak one", async ({
    page,
  }) => {
    await signIn(page, ada);
    await page.goto(`/goals/${firstGoalId}/learn/${lessonItemId}`);

    await pressUntil(
      page.getByRole("button", { name: "Practise these parts" }),
      page.getByText("Writing your quiz").or(page.getByRole("link", { name: "Take the quiz" })),
    );
    await expect(page.getByRole("link", { name: "Take the quiz" })).toBeVisible({
      timeout: 45_000,
    });
    await page.getByRole("link", { name: "Take the quiz" }).click();
    practiceQuizId = page.url().split("/quiz/")[1] ?? "";
    expect(practiceQuizId).not.toBe(quizId);
    await expect(page.getByText("Practice quiz", { exact: true }).first()).toBeVisible();

    await answerQuizCorrectly(page);
    await expect(page.getByText("5 of 5 answered")).toBeVisible();
    await page.getByRole("button", { name: "Submit answers" }).click();
    await expect(page).toHaveURL(/\/results\/[0-9a-f-]{36}$/);

    // The short answer is marked in the background, and labelled as an estimate.
    await expect(page.getByText("AI estimate").first()).toBeVisible({ timeout: 45_000 });
    await expect(page.getByText(/An AI compared your answer with the rubric/)).toBeVisible();
    await expect(page.getByText("100%").first()).toBeVisible();
    // One good quiz does not wipe out the earlier one: 1 part newest to 0.7 parts older, 59%.
    await expect(page.getByText("59%").first()).toBeVisible();
    await expect(page.getByText("Needs practice").first()).toBeVisible();
  });

  test("a third good quiz moves the topic to 'getting there' and the next step moves on", async ({
    page,
  }) => {
    await signIn(page, ada);
    await page.goto(`/goals/${firstGoalId}/learn/${lessonItemId}`);

    // At 59% the topic still needs practice, so the recommendation is still a practice quiz.
    await pressUntil(
      page.getByRole("button", { name: "Practise these parts" }),
      page.getByText("Writing your quiz").or(page.getByRole("link", { name: "Take the quiz" })),
    );
    await expect(page.getByRole("link", { name: "Take the quiz" })).toBeVisible({
      timeout: 45_000,
    });
    await page.getByRole("link", { name: "Take the quiz" }).click();
    await answerQuizCorrectly(page);
    await page.getByRole("button", { name: "Submit answers" }).click();
    await expect(page).toHaveURL(/\/results\/[0-9a-f-]{36}$/);
    thirdAttemptUrl = page.url();

    await expect(page.getByText("AI estimate").first()).toBeVisible({ timeout: 45_000 });
    await expect(page.getByText("78%").first()).toBeVisible();
    await expect(page.getByText("Getting there").first()).toBeVisible();
    // The weak topic is no longer the priority: the next step is the next topic of the roadmap.
    // (Next keeps the previous page, with its own recommendation, in the DOM: look at the visible one.)
    await expect(page.getByText("Your next step").locator("visible=true")).toBeVisible();
    await expect(page.getByRole("link", { name: "Continue studying" })).toBeVisible();
    await expect(page.getByText(/Start .*: it is the next topic on your roadmap/)).toBeVisible();
  });

  test("the learner can review the AI's marking of a short answer and the score follows", async ({
    page,
  }) => {
    await signIn(page, ada);
    await page.goto(thirdAttemptUrl);
    const before = await page.getByText(/\d+%/).first().innerText();
    expect(before).toBe("100%");

    const article = page.getByRole("article").last();
    await expect(article.getByText("AI estimate")).toBeVisible();
    await article.getByText("Disagree? Mark it yourself").click();
    for (const box of await article.getByRole("checkbox").all()) await box.uncheck();
    await article.getByRole("button", { name: "Save my marking" }).click();

    await expect(page.getByText("Your review is saved")).toBeVisible();
    const reviewed = page.getByRole("article").last();
    await expect(reviewed.getByText("Marked by you")).toBeVisible();
    await expect(reviewed.getByText("0 of 2 points")).toBeVisible();
    await expect(page.getByText("Includes your own marking")).toBeVisible();
    await expect(page.getByText(/^\d+%$/).first()).not.toHaveText("100%");

    // And it is still there after a reload.
    await page.reload();
    await expect(page.getByRole("article").last().getByText("Marked by you")).toBeVisible();
  });

  test("the goal page lists every topic with its mastery, and the dashboard shows where the learner stands", async ({
    page,
  }) => {
    await signIn(page, ada);

    await page.goto(`/goals/${firstGoalId}`);
    const topics = page.getByRole("list", { name: "Progress by topic" });
    await expect(topics.getByText(/Getting there|Needs practice/).first()).toBeVisible();
    await expect(topics.getByText("Not assessed yet").first()).toBeVisible();
    await expect(topics.getByRole("link", { name: /Results/ }).first()).toBeVisible();

    await page.goto("/dashboard");
    await expect(page.getByRole("heading", { name: "Where you stand" })).toBeVisible();
    await expect(page.getByText("Not assessed yet").first()).toBeVisible();
  });

  test("a text file is uploaded, read in the background and ready to use", async ({ page }) => {
    await signIn(page, ada);
    const token = await accessTokenOf(page.context());
    const topic = await topicWithoutLesson(page, token, firstGoalId);
    documentTopic = topic;
    documentText = textAbout(topic);

    await page.goto(`/goals/${firstGoalId}`);
    await expect(page.getByRole("heading", { name: "Study material" })).toBeVisible();
    await page.getByRole("link", { name: "Add study material" }).click();
    await expect(page).toHaveURL(new RegExp(`/goals/${firstGoalId}/documents$`));
    await expect(page.getByText("No study material yet")).toBeVisible();

    await page.getByLabel("File").setInputFiles({
      name: "rust-notes.txt",
      mimeType: "text/plain",
      buffer: Buffer.from(documentText),
    });
    await page.getByLabel(/Title/).first().fill("Rust notes");
    await page.getByRole("button", { name: "Upload" }).click();

    // The worker reads and indexes it; the page follows along by itself.
    await expect(page).toHaveURL(new RegExp(`/goals/${firstGoalId}/documents/[0-9a-f-]{36}$`));
    textDocumentId = page.url().split("/documents/")[1] ?? "";
    await expect(page.getByRole("heading", { level: 1, name: "Rust notes" })).toBeVisible();
    await expect(page.getByText("Ready to use", { exact: true })).toBeVisible({
      timeout: 45_000,
    });
    await expect(page.getByRole("heading", { name: "Extracted text" })).toBeVisible();
    await expect(page.getByText("every value has exactly one owner").first()).toBeVisible();
  });

  test("the original comes back as a download, and a reload keeps everything", async ({ page }) => {
    await signIn(page, ada);
    await page.goto(`/goals/${firstGoalId}/documents/${textDocumentId}`);

    const download = page.waitForEvent("download");
    await page.getByRole("link", { name: /Download original/ }).click();
    const file = await download;
    expect(file.suggestedFilename()).toBe("rust-notes.txt");
    const stream = await file.createReadStream();
    const chunks: Buffer[] = [];
    for await (const chunk of stream) chunks.push(chunk as Buffer);
    expect(Buffer.concat(chunks).toString("utf8")).toBe(documentText);

    await page.reload();
    await expect(page.getByText("Ready to use", { exact: true })).toBeVisible();
    await page.goto(`/goals/${firstGoalId}`);
    await expect(page.getByText(/1 document, 1 ready to use/)).toBeVisible();
  });

  test("search finds the real passage and says so when nothing covers a question", async ({
    page,
  }) => {
    await signIn(page, ada);
    await page.goto(`/goals/${firstGoalId}/documents`);

    await page.getByLabel("Question or keywords").fill(documentTopic.title);
    await page.getByRole("button", { name: "Search" }).click();
    await expect(page.getByText("1 passage found in 1 document.")).toBeVisible();
    const hit = page.getByRole("listitem").filter({ hasText: "exactly one owner" });
    await expect(hit.getByRole("link", { name: "Rust notes" })).toBeVisible();
    await expect(hit.getByText("part 1")).toBeVisible();

    await page.getByLabel("Question or keywords").fill("How do I bake sourdough bread at home");
    await page.getByRole("button", { name: "Search" }).click();
    await expect(page.getByText(/Nothing in your documents covers that/)).toBeVisible();
  });

  test("a file that is not what it says it is, or cannot be used, is refused with a reason", async ({
    page,
  }) => {
    await signIn(page, ada);
    await page.goto(`/goals/${firstGoalId}/documents`);
    const upload = async (name: string, mimeType: string, buffer: Buffer) => {
      await page.getByLabel("File").setInputFiles({ name, mimeType, buffer });
      await page.getByRole("button", { name: "Upload" }).click();
    };

    // Text pretending to be a PDF.
    await upload("fake.pdf", "application/pdf", Buffer.from("Just some words, not a PDF at all."));
    await expect(
      page.getByText(/file name ends in \.pdf but its content is plain text/i),
    ).toBeVisible();

    // A program pretending to be notes.
    await upload(
      "notes.txt",
      "text/plain",
      Buffer.from([0x4d, 0x5a, 0x90, 0x00, 0x03, 0x00, ...Array(200).fill(0)]),
    );
    await expect(page.getByText(/This kind of file can't be used/)).toBeVisible();

    // Nothing was stored for either.
    await expect(page.getByRole("link", { name: "fake", exact: true })).toHaveCount(0);
    await expect(page.getByRole("link", { name: "notes", exact: true })).toHaveCount(0);
  });

  test("a picture of notes is read, waits for the learner's check, and is used once confirmed", async ({
    page,
  }) => {
    await signIn(page, ada);
    await page.goto(`/goals/${firstGoalId}/documents`);

    await page.getByLabel("File").setInputFiles({
      name: "handwriting.png",
      mimeType: "image/png",
      buffer: Buffer.from(TINY_PNG, "base64"),
    });
    await page.getByLabel(/Title/).first().fill("Handwritten page");
    await page.getByRole("button", { name: "Upload" }).click();
    await expect(page).toHaveURL(new RegExp(`/goals/${firstGoalId}/documents/[0-9a-f-]{36}$`));
    imageDocumentId = page.url().split("/documents/")[1] ?? "";

    // The reading was uncertain, so nothing is used until the learner has looked at it.
    await expect(
      page.getByText("Check what was read before it is used", { exact: true }),
    ).toBeVisible({ timeout: 45_000 });
    await expect(page.getByText("Read from a picture", { exact: true })).toBeVisible();
    await expect(page.getByText("Partly unclear", { exact: true })).toBeVisible();
    const text = page.getByLabel("Text of page 1");
    await expect(text).toHaveValue(/Sample text from the built-in test provider/);

    await page.goto(`/goals/${firstGoalId}/documents`);
    await page.getByLabel("Question or keywords").fill("how long does a reference stay valid");
    await page.getByRole("button", { name: "Search" }).click();
    await expect(page.getByText(/Nothing in your documents covers that/)).toBeVisible();

    // Correct it, save, and use it.
    await page.goto(`/goals/${firstGoalId}/documents/${imageDocumentId}`);
    await page
      .getByLabel("Text of page 1")
      .fill(
        "Lifetimes describe how long a reference stays valid, so the compiler can reject dangling pointers.",
      );
    await page.getByRole("button", { name: "Save changes" }).click();
    await expect(page.getByText("Saved.", { exact: true })).toBeVisible();
    await expect(page.getByText("Corrected by you")).toBeVisible();
    await page.getByRole("button", { name: "Use this text" }).click();
    await expect(page.getByText("Ready to use", { exact: true })).toBeVisible({
      timeout: 45_000,
    });

    await page.goto(`/goals/${firstGoalId}/documents`);
    await page.getByLabel("Question or keywords").fill("how long does a reference stay valid");
    await page.getByRole("button", { name: "Search" }).click();
    await expect(
      page.getByText(/Lifetimes describe how long a reference stays valid/),
    ).toBeVisible();
  });

  test("a lesson written for a topic is grounded in the uploaded passage and cites it", async ({
    page,
  }) => {
    await signIn(page, ada);
    await page.goto(`/goals/${firstGoalId}/learn/${documentTopic.id}`);
    await expect(page.getByText("This topic doesn't have a lesson yet")).toBeVisible();

    await page.getByRole("button", { name: "Write this lesson" }).click();
    await expect(page.getByRole("button", { name: "Explain simply" })).toBeVisible({
      timeout: 45_000,
    });

    const sources = page
      .getByRole("heading", { name: "Sources" })
      .locator("xpath=ancestor::section");
    await expect(sources).toBeVisible();
    await expect(sources.getByRole("link", { name: "Rust notes" })).toBeVisible();
    await expect(sources.getByText("part 1").first()).toBeVisible();
    await expect(sources.getByText(/every value has exactly one owner/).first()).toBeVisible();
    await expect(page.getByText(/written from general knowledge/)).toHaveCount(0);
    // The lesson itself rests on the passage (the test provider quotes what it was given).
    await expect(page.getByText(/From Rust notes/).first()).toBeVisible();

    await sources.getByRole("link", { name: "Rust notes" }).click();
    await expect(page).toHaveURL(new RegExp(`/documents/${textDocumentId}$`));
  });

  test("deleting a document removes it and its passages, and the lesson shows the citation as gone", async ({
    page,
  }) => {
    await signIn(page, ada);
    await page.goto(`/goals/${firstGoalId}/documents/${textDocumentId}`);

    await page.getByRole("button", { name: "Delete" }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByText(/removed for good/)).toBeVisible();
    await dialog.getByRole("button", { name: "Delete forever" }).click();
    await expect(page).toHaveURL(
      new RegExp(`/goals/${firstGoalId}/documents\\?notice=document-deleted$`),
    );
    await expect(page.getByText("Document deleted", { exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "Rust notes" })).toHaveCount(0);

    // Its address is gone too, for the owner as for anyone.
    await page.goto(`/goals/${firstGoalId}/documents/${textDocumentId}`);
    await expect(page.getByText("We couldn't find that")).toBeVisible();

    // The search no longer returns it.
    await page.goto(`/goals/${firstGoalId}/documents`);
    await page.getByLabel("Question or keywords").fill(documentTopic.title);
    await page.getByRole("button", { name: "Search" }).click();
    await expect(
      page.getByText(/passages? found in|Nothing in your documents covers that/),
    ).toBeVisible();
    await expect(page.getByText("Rust notes")).toHaveCount(0);

    // The lesson keeps its wording but not a copy of the document.
    await page.goto(`/goals/${firstGoalId}/learn/${documentTopic.id}`);
    const sources = page
      .getByRole("heading", { name: "Sources" })
      .locator("xpath=ancestor::section");
    await expect(sources.getByText("A document you have since deleted")).toBeVisible();
    await expect(sources.getByText(/every value has exactly one owner/)).toHaveCount(0);
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
    let adasDocumentId = "";

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

      // And a document, uploaded through the API (what a document is does not depend on a browser).
      const upload = await page.request.post(
        `${API_URL}/v1/goals/${adasGoalId}/documents?name=ada-notes.txt&title=Ada%20notes`,
        {
          headers: { ...bearer(adasToken), "Content-Type": "application/octet-stream" },
          data: Buffer.from("Ada keeps her private study notes about ownership and borrowing."),
        },
      );
      expect(upload.status()).toBe(202);
      adasDocumentId = (await upload.json()).id;
      expect(adasDocumentId).toBeTruthy();

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

    test("cannot read, take, review or re-mark Ada's quizzes even with a real token", async ({
      browser,
      request,
    }) => {
      const other = await freshContext(browser);
      try {
        await signIn(other.page, grace);
        const token = await accessTokenOf(other.context);

        // Ada's first goal has the quizzes; the API answers 404 to everything, as for a missing id.
        const missing = "00000000-0000-4000-8000-000000000000";
        const attempts = [
          await request.get(`${API_URL}/v1/quizzes/${quizId}`, { headers: bearer(token) }),
          await request.post(`${API_URL}/v1/quizzes/${quizId}/attempts`, {
            headers: bearer(token),
            data: { answers: [] },
          }),
          await request.get(`${API_URL}/v1/quiz-attempts/${attemptId}`, {
            headers: bearer(token),
          }),
          await request.post(`${API_URL}/v1/quiz-attempts/${attemptId}/regrade`, {
            headers: bearer(token),
          }),
          await request.put(`${API_URL}/v1/quiz-answers/${missing}/review`, {
            headers: bearer(token),
            data: { met_point_ids: [] },
          }),
          await request.get(`${API_URL}/v1/roadmap-items/${lessonItemId}/assessment`, {
            headers: bearer(token),
          }),
          await request.post(`${API_URL}/v1/roadmap-items/${lessonItemId}/quizzes`, {
            headers: bearer(token),
            data: {},
          }),
          await request.get(`${API_URL}/v1/goals/${firstGoalId}/progress`, {
            headers: bearer(token),
          }),
        ];
        expect(attempts.map((response) => response.status())).toEqual([
          404, 404, 404, 404, 404, 404, 404, 404,
        ]);

        // Her pages for Ada's quiz and results look like pages that don't exist.
        await other.page.goto(`/goals/${firstGoalId}/learn/${lessonItemId}/quiz/${quizId}`);
        await expect(other.page.getByText("We couldn't find that")).toBeVisible();
        await other.page.goto(`/goals/${firstGoalId}/learn/${lessonItemId}/results/${attemptId}`);
        await expect(other.page.getByText("We couldn't find that")).toBeVisible();
      } finally {
        await other.context.close();
      }
    });

    test("cannot read, search, change, download or delete Ada's documents even with a real token", async ({
      browser,
      request,
    }) => {
      const other = await freshContext(browser);
      try {
        await signIn(other.page, grace);
        const token = await accessTokenOf(other.context);
        const document = `${API_URL}/v1/documents/${adasDocumentId}`;

        const attempts = [
          await request.get(`${API_URL}/v1/goals/${adasGoalId}/documents`, {
            headers: bearer(token),
          }),
          await request.post(`${API_URL}/v1/goals/${adasGoalId}/documents/search`, {
            headers: bearer(token),
            data: { query: "borrowing a value without ownership" },
          }),
          await request.post(`${API_URL}/v1/goals/${adasGoalId}/documents/paste`, {
            headers: bearer(token),
            data: { title: "Planted", text: "Planted text" },
          }),
          await request.post(`${API_URL}/v1/goals/${adasGoalId}/documents?name=planted.txt`, {
            headers: { ...bearer(token), "Content-Type": "application/octet-stream" },
            data: Buffer.from("Planted text"),
          }),
          await request.get(document, { headers: bearer(token) }),
          await request.get(`${document}/pages`, { headers: bearer(token) }),
          await request.get(`${document}/file`, { headers: bearer(token) }),
          await request.patch(document, { headers: bearer(token), data: { title: "Hijacked" } }),
          await request.put(`${document}/pages/1`, {
            headers: bearer(token),
            data: { text: "Hijacked" },
          }),
          await request.post(`${document}/confirm`, { headers: bearer(token) }),
          await request.post(`${document}/reprocess`, { headers: bearer(token) }),
          await request.delete(document, { headers: bearer(token) }),
        ];
        expect(attempts.map((response) => response.status())).toEqual(
          Array.from({ length: attempts.length }, () => 404),
        );

        // Her pages look exactly like pages that don't exist.
        for (const path of [
          `/goals/${adasGoalId}/documents`,
          `/goals/${adasGoalId}/documents/${adasDocumentId}`,
        ]) {
          await other.page.goto(path);
          await expect(other.page.getByText("We couldn't find that")).toBeVisible();
        }
        const download = await other.page.request.get(
          `/goals/${adasGoalId}/documents/${adasDocumentId}/file`,
        );
        expect(download.status()).toBe(404);
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
