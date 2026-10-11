import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const nav = vi.hoisted(() => ({ refresh: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: nav.refresh }) }));

const actions = vi.hoisted(() => ({
  saveProgressAction: vi.fn(),
  generateLessonAction: vi.fn(),
  cancelLessonAction: vi.fn(),
  retryLessonAction: vi.fn(),
}));
vi.mock("@/lib/lessons/actions", () => actions);

import { LessonContents } from "@/components/lesson/lesson-contents";
import { LessonGenerationStatus } from "@/components/lesson/lesson-generation-status";
import {
  LessonReader,
  SAVE_AFTER_READING_MS,
  SAVE_AFTER_TICK_MS,
} from "@/components/lesson/lesson-reader";
import { LessonVersions } from "@/components/lesson/lesson-versions";
import { NewVersionDialog } from "@/components/lesson/new-version-dialog";
import { TopicNavigation } from "@/components/lesson/topic-navigation";
import { POLL_INTERVAL_MS } from "@/components/jobs/job-progress";
import { RoadmapPanel } from "@/components/roadmap/roadmap-panel";
import { RoadmapView } from "@/components/roadmap/roadmap-view";
import type { LessonDocument, ProgressState, Roadmap, RoadmapItem } from "@/lib/api/server";
import {
  document as lessonDocument,
  GOAL,
  ITEM,
  JOB,
  LESSON,
  NEXT_ITEM,
  lesson,
  lessonJob,
  outline,
  progress,
  study,
} from "@/test-support/lessons";

type ReaderProps = Partial<Parameters<typeof LessonReader>[0]>;

function renderReader(props: ReaderProps = {}) {
  return render(
    <LessonReader
      goalId={GOAL}
      itemId={ITEM}
      lesson={lesson()}
      progress={null}
      outline={outline()}
      previous={null}
      next={{ id: NEXT_ITEM, title: "Borrowing" }}
      readOnly={false}
      versionActions={<button type="button">Write another version</button>}
      {...props}
    />,
  );
}

/**
 * Pretend the page is scrolled so that each section's top is where `tops` says (in pixels from the
 * top of the screen), then tell the reader the page scrolled.
 */
function scrollTo(tops: Record<string, number>) {
  vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (this: Element) {
    const top = tops[this.id] ?? 10_000;
    return {
      top,
      bottom: top + 400,
      left: 0,
      right: 0,
      width: 0,
      height: 400,
      x: 0,
      y: top,
    } as DOMRect;
  });
  act(() => {
    window.dispatchEvent(new Event("scroll"));
  });
}

beforeEach(() => {
  actions.saveProgressAction.mockResolvedValue({ ok: true });
  Element.prototype.scrollIntoView = vi.fn();
  window.scrollTo = vi.fn();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

// --- Rendering the lesson ------------------------------------------------------------------------

describe("the lesson on screen", () => {
  it("shows the objectives and every section under its own heading", () => {
    renderReader();

    expect(screen.getByRole("heading", { name: "What you will learn" })).toBeInTheDocument();
    expect(screen.getByText("Explain what ownership means")).toBeInTheDocument();
    const article = screen.getByRole("article", { name: "Ownership in Rust" });
    for (const heading of ["What ownership is", "Borrowing", "Putting it together"]) {
      expect(within(article).getByRole("heading", { level: 2, name: heading })).toBeInTheDocument();
    }
  });

  it("renders each kind of block from its typed fields", () => {
    const { container } = renderReader();

    // paragraph with inline `code` and **bold**
    expect(screen.getByText("one owner").tagName).toBe("STRONG");
    expect(screen.getByText("owner", { selector: "code" })).toBeInTheDocument();
    // unordered and ordered lists
    expect(container.querySelector("ul.list-disc")).not.toBeNull();
    expect(container.querySelector("ol.list-decimal")).not.toBeNull();
    expect(screen.getByText("Take a reference")).toBeInTheDocument();
    // code block, labelled and keyboard-scrollable, with its caption
    const code = screen.getByLabelText("Code example in rust");
    expect(code.tagName).toBe("PRE");
    expect(code).toHaveAttribute("tabindex", "0");
    expect(code).toHaveTextContent("let a = String::new();");
    expect(screen.getByText("A value")).toBeInTheDocument();
    // callouts are labelled notes, not live alerts
    expect(screen.getByRole("note", { name: "Remember" })).toHaveTextContent("single key");
    expect(screen.getByRole("note", { name: "Watch out" })).toHaveTextContent("mutate");
    expect(screen.getByRole("note", { name: "Note" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows key terms, worked examples, common mistakes and the summary", () => {
    renderReader();

    expect(screen.getByRole("heading", { name: "Key terms" })).toBeInTheDocument();
    expect(screen.getByText("Owner")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Worked examples" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Moving a string" })).toBeInTheDocument();
    expect(screen.getByText("The old name is invalid.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Common mistakes" })).toBeInTheDocument();
    expect(screen.getByText("Assignment always copies.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Summary" })).toBeInTheDocument();
    expect(screen.getByText("One owner at a time.")).toBeInTheDocument();
  });

  it("leaves out the parts a lesson does not have", () => {
    renderReader({
      lesson: lesson({
        content: lessonDocument({
          definitions: [],
          common_misconceptions: [],
          worked_examples: [],
        }),
      }),
    });

    expect(screen.queryByRole("heading", { name: "Key terms" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Common mistakes" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Worked examples" })).not.toBeInTheDocument();
  });

  it("never turns lesson text into markup, links or scripts", () => {
    const hostile =
      '<script>window.hacked=1</script> <img src=x onerror="window.hacked=1"> [x](javascript:1)';
    const content: LessonDocument = lessonDocument({
      sections: [
        {
          id: "s1",
          heading: "Plain heading <b>x</b>",
          blocks: [
            { type: "paragraph", text: hostile },
            { type: "list", ordered: false, items: [hostile] },
            { type: "callout", kind: "note", title: hostile, text: hostile },
            { type: "code", language: "html", code: hostile },
          ],
        },
      ],
      summary: [hostile, "second point"],
    });

    const { container } = renderReader({ lesson: lesson({ content }) });

    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("a[href^='javascript']")).toBeNull();
    expect(screen.getAllByText(hostile, { exact: false }).length).toBeGreaterThan(2);
    expect(screen.getByRole("heading", { name: "Plain heading <b>x</b>" })).toBeInTheDocument();
  });

  it("says plainly that a lesson without sources comes from general knowledge", () => {
    renderReader();

    expect(screen.getByText(/written from general knowledge/i)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Sources" })).not.toBeInTheDocument();
  });

  it("lists the passages of the learner's own material that a lesson cites", () => {
    renderReader({
      lesson: lesson({
        content: lessonDocument({
          source_references: [
            { source_id: "notes-1", chunk_id: "p7", note: "Defines ownership" },
            { source_id: "notes-1", chunk_id: "p9", note: null },
          ],
        }),
      }),
    });

    const sources = screen.getByRole("heading", { name: "Sources" }).closest("section");
    expect(sources).not.toBeNull();
    expect(within(sources as HTMLElement).getAllByRole("listitem")).toHaveLength(2);
    expect(within(sources as HTMLElement).getByText("Defines ownership")).toBeInTheDocument();
    expect(screen.queryByText(/written from general knowledge/i)).not.toBeInTheDocument();
  });

  it("labels a sample lesson, an earlier version and a requested change", () => {
    renderReader({
      lesson: lesson({ is_synthetic: true, status: "superseded", version: 2, adjust: "simpler" }),
    });

    expect(screen.getByText("Sample lesson")).toBeInTheDocument();
    expect(screen.getByText("Earlier version")).toBeInTheDocument();
    expect(screen.getByText("Simpler")).toBeInTheDocument();
    expect(screen.getByText("Version 2")).toBeInTheDocument();
    expect(screen.getByText(/built-in test provider, not an AI model/i)).toBeInTheDocument();
  });

  it("credits a real model without claiming a person reviewed the lesson", () => {
    renderReader();

    expect(screen.getByText(/gemini-3\.6-flash/)).toBeInTheDocument();
    expect(screen.getByText(/has not been reviewed by a person/i)).toBeInTheDocument();
  });
});

// --- Explain simply -----------------------------------------------------------------------------

describe("Explain simply", () => {
  it("shows the stored simple explanation on request and hides it again", async () => {
    const user = userEvent.setup();
    renderReader();
    expect(screen.queryByRole("heading", { name: "In simple words" })).not.toBeInTheDocument();

    const toggle = screen.getByRole("button", { name: "Explain simply" });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    await user.click(toggle);

    expect(screen.getByRole("heading", { name: "In simple words" })).toBeInTheDocument();
    expect(screen.getByText(/a toy that only one child can hold/i)).toBeInTheDocument();
    expect(screen.getByText(/library book with one borrower/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Hide the simple explanation" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    await user.click(screen.getByRole("button", { name: "Hide the simple explanation" }));
    expect(screen.queryByRole("heading", { name: "In simple words" })).not.toBeInTheDocument();
  });

  it("works without an analogy and makes no request to the server", async () => {
    const user = userEvent.setup();
    renderReader({
      lesson: lesson({
        content: lessonDocument({
          simple_explanation: { paragraphs: ["Just this."], analogy: null },
        }),
      }),
    });

    await user.click(screen.getByRole("button", { name: "Explain simply" }));

    expect(screen.getByText("Just this.")).toBeInTheDocument();
    expect(screen.queryByText(/think of it like this/i)).not.toBeInTheDocument();
    expect(actions.generateLessonAction).not.toHaveBeenCalled();
  });
});

// --- Progress, saving and resuming --------------------------------------------------------------

describe("tracking progress", () => {
  it("shows how much of the lesson is done, from the saved progress", () => {
    renderReader({
      progress: progress({ completed_section_ids: ["s1"], current_section_id: "s2" }),
    });

    expect(screen.getAllByText("1 of 3 sections done").length).toBeGreaterThan(0);
  });

  it("saves ticked sections together, a moment after the last tick", async () => {
    renderReader();

    // Both ticks happen at once (no typing delay between them), so a slow machine cannot let the
    // first tick's save fire before the second tick arrives.
    fireEvent.click(
      screen.getByRole("button", { name: /Mark section as done for What ownership is/ }),
    );
    fireEvent.click(screen.getByRole("button", { name: /Mark section as done for Borrowing/ }));

    expect(actions.saveProgressAction).not.toHaveBeenCalled();
    await waitFor(() => expect(actions.saveProgressAction).toHaveBeenCalledTimes(1), {
      timeout: SAVE_AFTER_TICK_MS * 4,
    });
    expect(actions.saveProgressAction).toHaveBeenCalledWith(GOAL, ITEM, LESSON, {
      completedSectionIds: ["s1", "s2"],
      currentSectionId: "s2", // the last section ticked is where the learner is
      completed: false,
    });
    expect(await screen.findByText("Progress saved")).toBeInTheDocument();
  });

  it("lets a ticked section be undone", async () => {
    const user = userEvent.setup();
    renderReader({ progress: progress({ completed_section_ids: ["s1"] }) });

    const undo = screen.getByRole("button", { name: /Done: undo/ });
    expect(undo).toHaveAttribute("aria-pressed", "true");
    await user.click(undo);

    await waitFor(() => expect(actions.saveProgressAction).toHaveBeenCalled());
    expect(actions.saveProgressAction.mock.calls[0]?.[3]).toMatchObject({
      completedSectionIds: [],
    });
  });

  it("finishes the lesson: every section done, saved at once, and the next topic offered", async () => {
    const user = userEvent.setup();
    renderReader();

    await user.click(screen.getByRole("button", { name: "Finish lesson" }));

    await waitFor(() => expect(actions.saveProgressAction).toHaveBeenCalledTimes(1));
    expect(actions.saveProgressAction).toHaveBeenCalledWith(GOAL, ITEM, LESSON, {
      completedSectionIds: ["s1", "s2", "s3"],
      currentSectionId: "s3",
      completed: true,
    });
    expect(screen.getByRole("heading", { name: "Lesson complete" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Next topic: Borrowing/ })).toHaveAttribute(
      "href",
      `/goals/${GOAL}/learn/${NEXT_ITEM}`,
    );
    expect(screen.getAllByText("Lesson finished").length).toBeGreaterThan(0);
  });

  it("can take a finished lesson back to unfinished", async () => {
    const user = userEvent.setup();
    renderReader({
      progress: progress({ status: "completed", completed_section_ids: ["s1", "s2", "s3"] }),
    });

    await user.click(screen.getByRole("button", { name: "Mark as not finished" }));

    await waitFor(() => expect(actions.saveProgressAction).toHaveBeenCalled());
    expect(actions.saveProgressAction.mock.calls[0]?.[3]).toMatchObject({ completed: false });
    expect(screen.getByRole("heading", { name: "Finished reading?" })).toBeInTheDocument();
  });

  it("follows the reading position and saves where the learner is", async () => {
    vi.useFakeTimers();
    renderReader();

    scrollTo({ s1: -900, s2: 120, s3: 700 }); // s2's top has reached the reading line
    expect(actions.saveProgressAction).not.toHaveBeenCalled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(SAVE_AFTER_READING_MS + 50);
    });

    expect(actions.saveProgressAction).toHaveBeenCalledWith(GOAL, ITEM, LESSON, {
      completedSectionIds: [],
      currentSectionId: "s2",
      completed: false,
    });
  });

  it("counts a jump straight to the end: the last section passed is where the learner is", async () => {
    vi.useFakeTimers();
    renderReader();

    scrollTo({ s1: -3000, s2: -2200, s3: -1500 });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(SAVE_AFTER_READING_MS + 50);
    });

    expect(actions.saveProgressAction.mock.calls[0]?.[3]).toMatchObject({
      currentSectionId: "s3",
    });
  });

  it("saves nothing before the learner has reached the first section", async () => {
    vi.useFakeTimers();
    renderReader();

    scrollTo({ s1: 600, s2: 1400, s3: 2200 }); // still on the objectives
    await act(async () => {
      await vi.advanceTimersByTimeAsync(SAVE_AFTER_READING_MS * 2);
    });

    expect(actions.saveProgressAction).not.toHaveBeenCalled();
  });

  it("does not save again when the reader has not moved", async () => {
    vi.useFakeTimers();
    renderReader({ progress: progress({ current_section_id: "s2" }) });

    scrollTo({ s1: -900, s2: 120, s3: 700 });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(SAVE_AFTER_READING_MS * 2);
    });

    expect(actions.saveProgressAction).not.toHaveBeenCalled();
  });

  it("stops following the page once the lesson is closed", () => {
    vi.useFakeTimers();
    const { unmount } = renderReader();
    unmount();

    scrollTo({ s1: -900, s2: 120, s3: 700 });

    expect(actions.saveProgressAction).not.toHaveBeenCalled();
  });

  it("saves what is pending when the learner leaves the lesson", async () => {
    const user = userEvent.setup();
    const { unmount } = renderReader();

    await user.click(screen.getByRole("button", { name: /Mark section as done for Borrowing/ }));
    expect(actions.saveProgressAction).not.toHaveBeenCalled();
    unmount();

    expect(actions.saveProgressAction).toHaveBeenCalledTimes(1);
    expect(actions.saveProgressAction.mock.calls[0]?.[3]).toMatchObject({
      completedSectionIds: ["s2"],
    });
  });

  it("keeps the lesson readable and offers a retry when saving fails", async () => {
    const user = userEvent.setup();
    actions.saveProgressAction.mockResolvedValueOnce({ ok: false, reason: "unavailable" });
    renderReader();

    await user.click(screen.getByRole("button", { name: "Finish lesson" }));

    expect(await screen.findByText("Your progress wasn’t saved")).toBeInTheDocument();
    expect(screen.getByText(/You can keep reading/)).toBeInTheDocument();
    expect(screen.getByRole("article")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Try saving again" }));
    await waitFor(() =>
      expect(screen.queryByText("Your progress wasn’t saved")).not.toBeInTheDocument(),
    );
    expect(actions.saveProgressAction).toHaveBeenCalledTimes(2);
  });

  it("tells the learner when their session ended, and when the goal is archived", async () => {
    const user = userEvent.setup();
    actions.saveProgressAction.mockResolvedValueOnce({ ok: false, reason: "session" });
    const { unmount } = renderReader();
    await user.click(screen.getByRole("button", { name: "Finish lesson" }));
    expect(await screen.findByText(/session has ended/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Try saving again" })).not.toBeInTheDocument();
    unmount();

    actions.saveProgressAction.mockResolvedValueOnce({ ok: false, reason: "archived" });
    renderReader();
    await user.click(screen.getByRole("button", { name: "Finish lesson" }));
    expect(await screen.findByText(/archived, so its lessons are read-only/i)).toBeInTheDocument();
  });

  it("treats an action that throws like a failed save", async () => {
    const user = userEvent.setup();
    actions.saveProgressAction.mockRejectedValueOnce(new Error("network"));
    renderReader();

    await user.click(screen.getByRole("button", { name: "Finish lesson" }));

    expect(await screen.findByText("Your progress wasn’t saved")).toBeInTheDocument();
  });

  it("is read-only for an archived goal: nothing to tick and nothing saved", async () => {
    vi.useFakeTimers();
    renderReader({ readOnly: true });

    scrollTo({ s1: -900, s2: -400, s3: 100 });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(SAVE_AFTER_READING_MS * 2);
    });

    expect(screen.queryByRole("button", { name: /Mark section as done/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Finish lesson" })).not.toBeInTheDocument();
    expect(screen.getByText(/Read-only: this goal is archived/)).toBeInTheDocument();
    expect(actions.saveProgressAction).not.toHaveBeenCalled();
  });
});

describe("resuming a lesson", () => {
  const saved = (overrides: Partial<ProgressState> = {}) =>
    progress({ completed_section_ids: ["s1"], current_section_id: "s2", ...overrides });

  it("scrolls back to the section the learner left off at and says so", () => {
    renderReader({ progress: saved() });

    expect(Element.prototype.scrollIntoView).toHaveBeenCalledWith({ block: "start" });
    expect(screen.getByText("Welcome back")).toBeInTheDocument();
    expect(screen.getByText(/You left off at/)).toHaveTextContent("Borrowing");
  });

  it("starts at the top on a first visit, at the first section, and for a finished lesson", () => {
    const { unmount } = renderReader();
    expect(screen.queryByText("Welcome back")).not.toBeInTheDocument();
    unmount();

    const first = renderReader({ progress: saved({ current_section_id: "s1" }) });
    expect(screen.queryByText("Welcome back")).not.toBeInTheDocument();
    first.unmount();

    renderReader({ progress: saved({ status: "completed" }) });
    expect(screen.queryByText("Welcome back")).not.toBeInTheDocument();
    expect(Element.prototype.scrollIntoView).not.toHaveBeenCalled();
  });

  it("lets the learner start from the top instead", async () => {
    const user = userEvent.setup();
    renderReader({ progress: saved() });

    await user.click(screen.getByRole("button", { name: "Start from the top" }));

    expect(window.scrollTo).toHaveBeenCalledWith({ top: 0 });
    expect(screen.queryByText("Welcome back")).not.toBeInTheDocument();
  });

  it("lets the learner continue there from the banner", async () => {
    const user = userEvent.setup();
    renderReader({ progress: saved() });
    vi.mocked(Element.prototype.scrollIntoView).mockClear();

    await user.click(screen.getByRole("button", { name: "Continue there" }));

    expect(Element.prototype.scrollIntoView).toHaveBeenCalledWith({ block: "start" });
    expect(screen.queryByText("Welcome back")).not.toBeInTheDocument();
  });

  it("ignores a saved place that is not part of this lesson", () => {
    renderReader({ progress: saved({ current_section_id: "s9" }) });

    expect(screen.queryByText("Welcome back")).not.toBeInTheDocument();
  });
});

// --- The contents panel ---------------------------------------------------------------------------

describe("the contents", () => {
  it("lists the lesson's sections with what is done, and the roadmap's topics with their state", () => {
    renderReader({
      progress: progress({ completed_section_ids: ["s1"], current_section_id: "s2" }),
    });

    const side = screen.getByRole("complementary", { name: "Contents" });
    const sections = within(side).getByRole("navigation", { name: "In this lesson" });
    expect(
      within(sections).getByRole("link", { name: /What ownership is \(done\)/ }),
    ).toHaveAttribute("href", "#s1");
    expect(within(sections).getByRole("link", { name: "Borrowing" })).toHaveAttribute(
      "aria-current",
      "location",
    );

    const topics = within(side).getByRole("navigation", { name: "Roadmap topics" });
    expect(within(topics).getByRole("heading", { name: "Core ideas" })).toBeInTheDocument();
    expect(within(topics).getByRole("heading", { name: "Optional extras" })).toBeInTheDocument();
    const here = within(topics).getByRole("link", { name: /Ownership/ });
    expect(here).toHaveAttribute("aria-current", "page");
    expect(here).toHaveTextContent("1 of 3 sections");
    expect(within(topics).getByRole("link", { name: /Borrowing/ })).toHaveTextContent(
      "Not started",
    );
    expect(within(topics).getByRole("link", { name: /Optional extra/ })).toHaveTextContent("Done");
    expect(within(topics).getByRole("link", { name: /Borrowing/ })).toHaveAttribute(
      "href",
      `/goals/${GOAL}/learn/${NEXT_ITEM}`,
    );
  });

  it("is reachable on small screens through a Contents button, and closes after a choice", async () => {
    const user = userEvent.setup();
    renderReader();

    await user.click(screen.getByRole("button", { name: /Contents/ }));
    const sheet = await screen.findByRole("dialog", { name: "Contents" });
    expect(within(sheet).getByRole("navigation", { name: "In this lesson" })).toBeInTheDocument();
    expect(within(sheet).getByRole("navigation", { name: "Roadmap topics" })).toBeInTheDocument();

    await user.click(within(sheet).getByRole("link", { name: "Borrowing" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("gives the two copies of the contents different ids", async () => {
    const user = userEvent.setup();
    const { container } = renderReader();
    await user.click(screen.getByRole("button", { name: /Contents/ }));
    await screen.findByRole("dialog");

    const ids = [...document.querySelectorAll("[id]")].map((element) => element.id);
    expect(new Set(ids).size).toBe(ids.length);
    expect(container).toBeTruthy();
  });

  it("shows no module heading for an empty outline entry list", () => {
    render(
      <LessonContents
        goalId={GOAL}
        sections={[]}
        doneIds={new Set()}
        currentId={null}
        outline={[]}
        currentItemId={ITEM}
        idPrefix="x"
      />,
    );

    expect(screen.queryAllByRole("heading", { level: 3 })).toHaveLength(0);
  });
});

describe("moving between topics", () => {
  it("links to the previous and next topic", () => {
    render(
      <TopicNavigation
        goalId={GOAL}
        previous={{ id: ITEM, title: "Ownership" }}
        next={{ id: NEXT_ITEM, title: "Borrowing" }}
      />,
    );

    const nav = screen.getByRole("navigation", { name: "Topic navigation" });
    expect(within(nav).getByRole("link", { name: /Previous topic/ })).toHaveAttribute(
      "href",
      `/goals/${GOAL}/learn/${ITEM}`,
    );
    expect(within(nav).getByRole("link", { name: /Next topic/ })).toHaveAttribute(
      "href",
      `/goals/${GOAL}/learn/${NEXT_ITEM}`,
    );
  });

  it("has no previous link on the first topic and points back to the roadmap after the last", () => {
    render(<TopicNavigation goalId={GOAL} previous={null} next={null} />);

    expect(screen.queryByRole("link", { name: /Previous topic/ })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Back to the roadmap/ })).toHaveAttribute(
      "href",
      `/goals/${GOAL}/roadmap`,
    );
  });
});

// --- A lesson being written -----------------------------------------------------------------------

describe("LessonGenerationStatus", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  it("shows the stage and progress, and refreshes the page while the job runs", () => {
    const { unmount } = render(
      <LessonGenerationStatus goalId={GOAL} itemId={ITEM} job={lessonJob()} />,
    );

    expect(screen.getByText("Writing your lesson")).toBeInTheDocument();
    expect(screen.getAllByText("Writing your lesson…").length).toBeGreaterThan(0);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "20");
    expect(nav.refresh).not.toHaveBeenCalled();
    act(() => vi.advanceTimersByTime(POLL_INTERVAL_MS * 3));
    expect(nav.refresh).toHaveBeenCalledTimes(3);

    unmount();
    act(() => vi.advanceTimersByTime(POLL_INTERVAL_MS * 5));
    expect(nav.refresh).toHaveBeenCalledTimes(3);
  });

  it("can be cancelled through the bound action", () => {
    render(<LessonGenerationStatus goalId={GOAL} itemId={ITEM} job={lessonJob()} />);

    screen.getByRole("button", { name: "Cancel" }).click();

    expect(actions.cancelLessonAction).toHaveBeenCalledWith(GOAL, ITEM, JOB, expect.anything());
  });

  it("shows that it is stopping once a cancel has been asked for", () => {
    render(
      <LessonGenerationStatus
        goalId={GOAL}
        itemId={ITEM}
        job={lessonJob({ cancel_requested: true })}
      />,
    );

    expect(screen.getByText("Stopping…")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel" })).not.toBeInTheDocument();
  });

  it("says which attempt a retried job is on", () => {
    render(
      <LessonGenerationStatus
        goalId={GOAL}
        itemId={ITEM}
        job={lessonJob({ status: "queued", stage: "waiting_retry", attempts: 1 })}
      />,
    );

    expect(screen.getByText("Attempt 2 of 3.")).toBeInTheDocument();
    expect(screen.getAllByText(/busy/i).length).toBeGreaterThan(0);
  });

  it("says a job that is running its second try is a retry, not a crash", () => {
    render(
      <LessonGenerationStatus
        goalId={GOAL}
        itemId={ITEM}
        job={lessonJob({ status: "running", stage: "loading", progress: 5, attempts: 2 })}
      />,
    );

    expect(screen.getByText("Attempt 2 of 3.")).toBeInTheDocument();
    expect(screen.getByText(/tried again/)).toBeInTheDocument();
  });

  it("does not mention a retry on the first try", () => {
    render(
      <LessonGenerationStatus
        goalId={GOAL}
        itemId={ITEM}
        job={lessonJob({ status: "running", stage: "writing", attempts: 1 })}
      />,
    );

    expect(screen.queryByText(/Attempt/)).not.toBeInTheDocument();
  });

  it("explains that the current lesson stays while a new version is written", () => {
    render(<LessonGenerationStatus goalId={GOAL} itemId={ITEM} job={lessonJob()} newVersion />);

    expect(screen.getByText("Writing a new version of this lesson")).toBeInTheDocument();
    expect(screen.getByText(/lesson below stays available/i)).toBeInTheDocument();
  });
});

// --- Asking for another version -------------------------------------------------------------------

describe("NewVersionDialog", () => {
  it("offers the three adjustments and a note, and asks for a regeneration", async () => {
    const user = userEvent.setup();
    render(<NewVersionDialog goalId={GOAL} itemId={ITEM} />);

    await user.click(screen.getByRole("button", { name: "Write another version" }));
    const dialog = await screen.findByRole("dialog");

    const choices = within(dialog).getAllByRole("radio");
    expect(choices.map((c) => (c as HTMLInputElement).value)).toEqual([
      "",
      "simpler",
      "more_examples",
      "deeper",
    ]);
    expect(within(dialog).getByRole("radio", { name: /Just write it again/ })).toBeChecked();
    expect(within(dialog).getByRole("textbox")).toHaveAttribute("maxlength", "300");
    expect(dialog.querySelector("input[name=regenerate]")).toHaveValue("1");
  });

  it("submits the chosen adjustment and note to the lesson action for this topic", async () => {
    const user = userEvent.setup();
    render(<NewVersionDialog goalId={GOAL} itemId={ITEM} />);
    await user.click(screen.getByRole("button", { name: "Write another version" }));
    const dialog = await screen.findByRole("dialog");

    await user.click(within(dialog).getByRole("radio", { name: /Simpler/ }));
    await user.type(within(dialog).getByRole("textbox"), "use cooking");
    await user.click(within(dialog).getByRole("button", { name: "Write the new version" }));

    await waitFor(() => expect(actions.generateLessonAction).toHaveBeenCalledTimes(1));
    const [goal, item, data] = actions.generateLessonAction.mock.calls[0] as [
      string,
      string,
      FormData,
    ];
    expect([goal, item]).toEqual([GOAL, ITEM]);
    expect(data.get("adjust")).toBe("simpler");
    expect(data.get("feedback")).toBe("use cooking");
    expect(data.get("regenerate")).toBe("1");
  });
});

describe("LessonVersions", () => {
  const versions = [
    {
      id: "a",
      version: 2,
      status: "current" as const,
      title: "t",
      adjust: "simpler" as const,
      is_synthetic: false,
      created_at: "2026-10-12T10:00:00Z",
    },
    {
      id: "b",
      version: 1,
      status: "superseded" as const,
      title: "t",
      adjust: null,
      is_synthetic: true,
      created_at: "2026-10-11T10:00:00Z",
    },
  ];

  it("is not shown when there is only one version", () => {
    const { container } = render(
      <LessonVersions
        goalId={GOAL}
        itemId={ITEM}
        versions={versions.slice(0, 1)}
        viewingId="a"
        timeZone="UTC"
      />,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it("lists every version and links to the ones not being read", () => {
    render(
      <LessonVersions
        goalId={GOAL}
        itemId={ITEM}
        versions={versions}
        viewingId="a"
        timeZone="UTC"
      />,
    );

    expect(screen.getByText("Version 2 (reading)")).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Version 1" })).toHaveAttribute(
      "href",
      `/goals/${GOAL}/learn/${ITEM}?lesson=b`,
    );
    expect(screen.getByText("Newest")).toBeInTheDocument();
    expect(screen.getByText("Simpler")).toBeInTheDocument();
    expect(screen.getByText("Sample lesson")).toBeInTheDocument();
  });
});

// --- Where the roadmap leads to a lesson ----------------------------------------------------------

describe("the roadmap leads to the lessons", () => {
  function item(id: string, overrides: Partial<RoadmapItem> = {}): RoadmapItem {
    return {
      id,
      kind: "topic",
      position: 1,
      key: id,
      title: `Topic ${id}`,
      description: "Described",
      practice_task: "Practise",
      objective_ids: [],
      estimated_minutes: 30,
      day_number: 1,
      prerequisite_ids: [],
      study: study(),
      ...overrides,
    };
  }

  function roadmapWith(topics: RoadmapItem[], overrides: Partial<Roadmap> = {}): Roadmap {
    return {
      id: "88888888-8888-4888-8888-888888888888",
      goal_id: GOAL,
      version: 1,
      status: "current",
      title: "Plan",
      language: "en",
      topic_count: topics.length,
      total_minutes: 90,
      total_days: 3,
      daily_minutes: 60,
      target_date: null,
      revision_feedback: null,
      based_on_roadmap_id: null,
      is_synthetic: false,
      completed_topics: 0,
      created_at: "2026-10-11T09:00:00Z",
      overview: "An overview of the plan.",
      target_outcome: "Be able to do it.",
      syllabus_basis: "general_knowledge",
      assumptions: [],
      unknowns: [],
      objectives: [{ id: "o1", text: "Do it" }],
      prompt_version: "roadmap-planner/v1",
      modules: [{ id: "m1", position: 1, title: "Module", summary: "S", topics }],
      revision_sessions: [
        item("rev", { kind: "revision", title: "Revise it", practice_task: null }),
      ],
      enrichment: [],
      ...overrides,
    };
  }

  it("gives each topic a study button that says what will happen, and none to a revision session", () => {
    render(
      <RoadmapView
        goalId={GOAL}
        roadmap={roadmapWith([
          item("a"),
          item("b", {
            study: study({
              status: "in_progress",
              has_lesson: true,
              sections_done: 1,
              sections_total: 3,
            }),
          }),
          item("c", { study: study({ status: "completed", has_lesson: true }) }),
        ])}
      />,
    );

    expect(screen.getByRole("link", { name: /Open lesson.*Topic a/ })).toHaveAttribute(
      "href",
      `/goals/${GOAL}/learn/a`,
    );
    expect(screen.getByRole("link", { name: /^Continue: Topic b$/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Review.*Topic c/ })).toBeInTheDocument();
    expect(screen.getByText("1 of 3 sections")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Revise it/ })).not.toBeInTheDocument();
  });

  it("shows the learner's progress and a Continue studying button for the topic in progress", () => {
    render(
      <RoadmapView
        goalId={GOAL}
        roadmap={roadmapWith(
          [
            item("a", { study: study({ status: "completed", has_lesson: true }) }),
            item("b", {
              study: study({
                status: "in_progress",
                has_lesson: true,
                sections_done: 1,
                sections_total: 3,
              }),
            }),
            item("c"),
          ],
          { completed_topics: 1, topic_count: 3 },
        )}
      />,
    );

    expect(screen.getByText("1 of 3 topics finished")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Continue studying:\s*Topic b/ })).toHaveAttribute(
      "href",
      `/goals/${GOAL}/learn/b`,
    );
  });

  it("starts with the first topic when nothing has been studied, and says when everything is done", () => {
    const { unmount } = render(
      <RoadmapView goalId={GOAL} roadmap={roadmapWith([item("a"), item("b")])} />,
    );
    expect(screen.getByRole("link", { name: /Start studying:\s*Topic a/ })).toBeInTheDocument();
    unmount();

    render(
      <RoadmapView
        goalId={GOAL}
        roadmap={roadmapWith(
          [item("a", { study: study({ status: "completed", has_lesson: true }) })],
          {
            completed_topics: 1,
            topic_count: 1,
          },
        )}
      />,
    );
    expect(screen.getByText(/Every topic is finished/)).toBeInTheDocument();
  });

  it("shows the goal's roadmap card with topics finished and a way to continue", () => {
    const current = {
      id: "99999999-9999-4999-8999-999999999999",
      goal_id: GOAL,
      version: 1,
      status: "current" as const,
      title: "Plan",
      language: "en",
      topic_count: 4,
      total_minutes: 120,
      total_days: 4,
      daily_minutes: 30,
      target_date: null,
      revision_feedback: null,
      based_on_roadmap_id: null,
      is_synthetic: false,
      completed_topics: 2,
      created_at: "2026-10-11T09:00:00Z",
    };

    render(
      <RoadmapPanel
        goalId={GOAL}
        goalStatus="active"
        state={{ kind: "ready", current, versions: 1 }}
        timeZone="UTC"
      />,
    );

    expect(screen.getByText("2 of 4 topics finished")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Continue studying/ })).toHaveAttribute(
      "href",
      `/goals/${GOAL}/roadmap`,
    );
  });

  it("offers no 'continue studying' on an archived goal, which is read-only", () => {
    const current = {
      id: "99999999-9999-4999-8999-999999999999",
      goal_id: GOAL,
      version: 1,
      status: "current" as const,
      title: "Plan",
      language: "en",
      topic_count: 4,
      total_minutes: 120,
      total_days: 4,
      daily_minutes: 30,
      target_date: null,
      revision_feedback: null,
      based_on_roadmap_id: null,
      is_synthetic: false,
      completed_topics: 2,
      created_at: "2026-10-11T09:00:00Z",
    };

    render(
      <RoadmapPanel
        goalId={GOAL}
        goalStatus="archived"
        state={{ kind: "ready", current, versions: 1 }}
        timeZone="UTC"
      />,
    );

    expect(screen.queryByRole("link", { name: /Continue studying/ })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /View roadmap/ })).toBeInTheDocument();
  });
});
