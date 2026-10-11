import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const nav = vi.hoisted(() => ({ refresh: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: nav.refresh }) }));

const actions = vi.hoisted(() => ({
  generateRoadmapAction: vi.fn(),
  cancelGenerationAction: vi.fn(),
  retryGenerationAction: vi.fn(),
  makeRoadmapCurrentAction: vi.fn(),
}));
vi.mock("@/lib/roadmaps/actions", () => actions);

import {
  GenerationStatus,
  POLL_INTERVAL_MS,
  SLOW_START_MS,
} from "@/components/roadmap/generation-status";
import { RegenerateDialog } from "@/components/roadmap/regenerate-dialog";
import { RoadmapPanel } from "@/components/roadmap/roadmap-panel";
import { RoadmapView } from "@/components/roadmap/roadmap-view";
import { VersionHistory } from "@/components/roadmap/version-history";
import type { GenerationJob, Roadmap, RoadmapItem, RoadmapSummary } from "@/lib/api/server";

const GOAL = "11111111-1111-4111-8111-111111111111";
const JOB = "22222222-2222-4222-8222-222222222222";

function job(overrides: Partial<GenerationJob> = {}): GenerationJob {
  return {
    id: JOB,
    goal_id: GOAL,
    job_type: "roadmap",
    status: "running",
    stage: "planning",
    progress: 20,
    attempts: 1,
    max_attempts: 3,
    cancel_requested: false,
    error_code: null,
    error_message: null,
    roadmap_id: null,
    created_at: "2026-10-11T10:00:00Z",
    started_at: "2026-10-11T10:00:01Z",
    finished_at: null,
    ...overrides,
  };
}

function summary(overrides: Partial<RoadmapSummary> = {}): RoadmapSummary {
  return {
    id: "33333333-3333-4333-8333-333333333333",
    goal_id: GOAL,
    version: 2,
    status: "current",
    title: "Learn Rust in a week",
    language: "en",
    topic_count: 6,
    total_minutes: 260,
    total_days: 7,
    daily_minutes: 60,
    target_date: null,
    revision_feedback: null,
    based_on_roadmap_id: null,
    is_synthetic: false,
    created_at: "2026-10-11T09:00:00Z",
    ...overrides,
  };
}

function item(overrides: Partial<RoadmapItem>): RoadmapItem {
  return {
    id: "item",
    kind: "topic",
    position: 1,
    key: "key",
    title: "Item",
    description: "Described",
    practice_task: "Practise",
    objective_ids: ["o1"],
    estimated_minutes: 30,
    day_number: 1,
    prerequisite_ids: [],
    ...overrides,
  };
}

function roadmap(overrides: Partial<Roadmap> = {}): Roadmap {
  const first = item({ id: "t1", position: 1, title: "Ownership", day_number: 1 });
  const second = item({
    id: "t2",
    position: 2,
    title: "Borrowing",
    day_number: 2,
    objective_ids: ["o1", "o2"],
    prerequisite_ids: ["t1"],
  });
  return {
    ...summary(),
    overview: "A short path through the basics.",
    target_outcome: "Write small command-line tools.",
    syllabus_basis: "general_knowledge",
    assumptions: ["You already know Python."],
    unknowns: ["Which edition of the book you use."],
    objectives: [
      { id: "o1", text: "Explain ownership" },
      { id: "o2", text: "Use references safely" },
    ],
    prompt_version: "roadmap-planner/v1",
    modules: [
      {
        id: "m1",
        position: 1,
        title: "Core ideas",
        summary: "The foundations.",
        topics: [first, second],
      },
    ],
    revision_sessions: [
      item({
        id: "r1",
        kind: "revision",
        position: 3,
        title: "Recall everything",
        description: "Explain each topic aloud.",
        practice_task: null,
        day_number: 3,
        prerequisite_ids: ["t1", "t2"],
        estimated_minutes: 20,
      }),
    ],
    enrichment: [
      item({
        id: "e1",
        kind: "enrichment",
        position: 4,
        title: "Read the compiler errors guide",
        practice_task: null,
        day_number: null,
      }),
    ],
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  for (const action of Object.values(actions)) action.mockResolvedValue(undefined);
});

afterEach(() => {
  vi.useRealTimers();
});

describe("GenerationStatus", () => {
  it("shows what the worker is doing and how far along it is", () => {
    render(<GenerationStatus goalId={GOAL} job={job()} />);

    expect(screen.getByText("Making your roadmap")).toBeInTheDocument();
    expect(screen.getAllByText(/Planning your roadmap/).length).toBeGreaterThan(0);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "20");
  });

  it("announces the stage politely for screen readers", () => {
    render(<GenerationStatus goalId={GOAL} job={job({ stage: "saving", progress: 85 })} />);

    const live = screen.getByRole("status");
    expect(live).toHaveAttribute("aria-live", "polite");
    expect(live).toHaveTextContent("Saving your roadmap… 85%");
  });

  it("asks the server for fresh state every couple of seconds, and stops when it goes away", () => {
    vi.useFakeTimers();
    const { unmount } = render(<GenerationStatus goalId={GOAL} job={job()} />);
    expect(nav.refresh).not.toHaveBeenCalled();

    act(() => vi.advanceTimersByTime(POLL_INTERVAL_MS * 3));
    expect(nav.refresh).toHaveBeenCalledTimes(3);

    unmount();
    act(() => vi.advanceTimersByTime(POLL_INTERVAL_MS * 5));
    expect(nav.refresh).toHaveBeenCalledTimes(3);
  });

  it("offers a cancel that is bound to this goal and job", async () => {
    const user = userEvent.setup();
    render(<GenerationStatus goalId={GOAL} job={job()} />);

    await user.click(screen.getByRole("button", { name: "Cancel" }));

    await waitFor(() => expect(actions.cancelGenerationAction).toHaveBeenCalledTimes(1));
    expect(actions.cancelGenerationAction.mock.calls[0]?.slice(0, 2)).toEqual([GOAL, JOB]);
  });

  it("shows 'Stopping…' instead of a second cancel once one was requested", () => {
    render(<GenerationStatus goalId={GOAL} job={job({ cancel_requested: true })} />);

    expect(screen.getByText("Stopping…")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel" })).not.toBeInTheDocument();
  });

  it("says which attempt it is on when it is trying again", () => {
    render(
      <GenerationStatus
        goalId={GOAL}
        job={job({ status: "queued", stage: "waiting_retry", attempts: 1, progress: 20 })}
      />,
    );

    expect(screen.getByText("Attempt 2 of 3.")).toBeInTheDocument();
    expect(screen.getAllByText(/busy/).length).toBeGreaterThan(0);
  });

  it("reassures when no worker has picked the job up for a while", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-11T10:00:10Z"));
    render(
      <GenerationStatus
        goalId={GOAL}
        job={job({ status: "queued", stage: "queued", attempts: 0, progress: 0 })}
      />,
    );
    expect(screen.queryByText(/taking longer than usual/i)).not.toBeInTheDocument();

    act(() => vi.advanceTimersByTime(SLOW_START_MS + 6_000));

    expect(screen.getByText(/taking longer than usual/i)).toBeInTheDocument();
  });
});

describe("RoadmapPanel", () => {
  it("invites the learner to generate a first roadmap", async () => {
    const user = userEvent.setup();
    render(
      <RoadmapPanel goalId={GOAL} goalStatus="active" state={{ kind: "none" }} timeZone="UTC" />,
    );

    expect(screen.getByRole("heading", { name: "Roadmap", level: 2 })).toBeInTheDocument();
    expect(screen.getByText("Turn this goal into a study plan")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Generate roadmap" }));

    await waitFor(() => expect(actions.generateRoadmapAction).toHaveBeenCalledTimes(1));
    expect(actions.generateRoadmapAction.mock.calls[0]?.[0]).toBe(GOAL);
  });

  it("does not offer to generate for an archived goal", () => {
    render(
      <RoadmapPanel goalId={GOAL} goalStatus="archived" state={{ kind: "none" }} timeZone="UTC" />,
    );

    expect(screen.queryByRole("button", { name: "Generate roadmap" })).not.toBeInTheDocument();
    expect(screen.getByText(/Restore this goal/)).toBeInTheDocument();
  });

  it("shows live progress while a job is running", () => {
    render(
      <RoadmapPanel
        goalId={GOAL}
        goalStatus="active"
        state={{ kind: "generating", job: job() }}
        timeZone="UTC"
      />,
    );

    expect(screen.getByText("Making your roadmap")).toBeInTheDocument();
  });

  it("explains a failure in the learner's terms and offers a way forward", async () => {
    const user = userEvent.setup();
    const failed = job({
      status: "failed",
      error_code: "AI_RATE_LIMITED",
      error_message: "The AI service is busy right now. Please try again in a few minutes.",
    });
    render(
      <RoadmapPanel
        goalId={GOAL}
        goalStatus="active"
        state={{ kind: "failed", job: failed, current: summary() }}
        timeZone="UTC"
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("We couldn’t make your roadmap");
    expect(screen.getByRole("alert")).toHaveTextContent("The AI service is busy right now");
    expect(screen.getByRole("link", { name: "Edit goal" })).toHaveAttribute(
      "href",
      `/goals/${GOAL}/edit`,
    );
    expect(screen.getByRole("link", { name: "View your previous roadmap" })).toHaveAttribute(
      "href",
      `/goals/${GOAL}/roadmap`,
    );
    await user.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(actions.retryGenerationAction).toHaveBeenCalledTimes(1));
    expect(actions.retryGenerationAction.mock.calls[0]?.slice(0, 2)).toEqual([GOAL, JOB]);
  });

  it("offers no previous roadmap link when there was none", () => {
    render(
      <RoadmapPanel
        goalId={GOAL}
        goalStatus="active"
        state={{
          kind: "failed",
          job: job({ status: "failed", error_message: "x" }),
          current: null,
        }}
        timeZone="UTC"
      />,
    );

    expect(screen.queryByRole("link", { name: /previous roadmap/ })).not.toBeInTheDocument();
  });

  it("an archived goal's failure has nothing to retry or edit", () => {
    render(
      <RoadmapPanel
        goalId={GOAL}
        goalStatus="archived"
        state={{
          kind: "failed",
          job: job({ status: "failed", error_message: "x" }),
          current: null,
        }}
        timeZone="UTC"
      />,
    );

    expect(screen.queryByRole("button", { name: "Try again" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Edit goal" })).not.toBeInTheDocument();
  });

  it("summarises the current roadmap and links to it", () => {
    render(
      <RoadmapPanel
        goalId={GOAL}
        goalStatus="active"
        state={{ kind: "ready", current: summary(), versions: 3 }}
        timeZone="UTC"
      />,
    );

    expect(screen.getByText("Learn Rust in a week")).toBeInTheDocument();
    expect(screen.getByText(/Version 2 of 3/)).toBeInTheDocument();
    expect(screen.getByText("Current")).toBeInTheDocument();
    expect(screen.getByText("4 h 20 min")).toBeInTheDocument();
    expect(screen.getByText("7 days")).toBeInTheDocument();
    expect(screen.queryByText("Sample plan")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /View roadmap/ })).toHaveAttribute(
      "href",
      `/goals/${GOAL}/roadmap`,
    );
    expect(screen.getByRole("button", { name: "Revise or regenerate" })).toBeInTheDocument();
  });

  it("labels a plan from the test provider as a sample", () => {
    render(
      <RoadmapPanel
        goalId={GOAL}
        goalStatus="active"
        state={{ kind: "ready", current: summary({ is_synthetic: true }), versions: 1 }}
        timeZone="UTC"
      />,
    );

    expect(screen.getByText("Sample plan")).toBeInTheDocument();
  });

  it("an archived goal's roadmap can be read but not revised", () => {
    render(
      <RoadmapPanel
        goalId={GOAL}
        goalStatus="archived"
        state={{ kind: "ready", current: summary(), versions: 1 }}
        timeZone="UTC"
      />,
    );

    expect(screen.getByRole("link", { name: /View roadmap/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Revise or regenerate/ })).not.toBeInTheDocument();
  });
});

describe("RegenerateDialog", () => {
  it("asks for an optional note and promises that nothing is lost", async () => {
    const user = userEvent.setup();
    render(<RegenerateDialog goalId={GOAL} hasRoadmap />);

    await user.click(screen.getByRole("button", { name: "Revise or regenerate" }));

    const dialog = await screen.findByRole("dialog", { name: "Make a new version" });
    expect(within(dialog).getByText(/every earlier version stay available/)).toBeInTheDocument();
    expect(within(dialog).getByLabelText(/What should change/)).toHaveAttribute("maxlength", "500");
  });

  it("sends the note with the goal it is for", async () => {
    const user = userEvent.setup();
    render(<RegenerateDialog goalId={GOAL} hasRoadmap />);
    await user.click(screen.getByRole("button", { name: "Revise or regenerate" }));
    const dialog = await screen.findByRole("dialog");

    await user.type(within(dialog).getByLabelText(/What should change/), "More practice please");
    await user.click(within(dialog).getByRole("button", { name: "Create new version" }));

    await waitFor(() => expect(actions.generateRoadmapAction).toHaveBeenCalledTimes(1));
    const [goalId, formData] = actions.generateRoadmapAction.mock.calls[0] ?? [];
    expect(goalId).toBe(GOAL);
    expect((formData as FormData).get("feedback")).toBe("More practice please");
  });

  it("can be dismissed without starting anything", async () => {
    const user = userEvent.setup();
    render(<RegenerateDialog goalId={GOAL} hasRoadmap />);
    await user.click(screen.getByRole("button", { name: "Revise or regenerate" }));

    await user.click(await screen.findByRole("button", { name: "Cancel" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(actions.generateRoadmapAction).not.toHaveBeenCalled();
  });

  it("words itself for a first roadmap", async () => {
    const user = userEvent.setup();
    render(<RegenerateDialog goalId={GOAL} hasRoadmap={false} />);

    await user.click(screen.getByRole("button", { name: "Generate roadmap" }));

    expect(await screen.findByRole("dialog", { name: "Generate a roadmap" })).toBeInTheDocument();
  });
});

describe("RoadmapView", () => {
  it("presents the overview, outcome and where the content comes from", () => {
    render(<RoadmapView roadmap={roadmap()} />);

    expect(screen.getByText("A short path through the basics.")).toBeInTheDocument();
    expect(screen.getByText(/Write small command-line tools/)).toBeInTheDocument();
    expect(screen.getByText(/not an official syllabus/)).toBeInTheDocument();
  });

  it("states what could not be verified and what was assumed, separately", () => {
    render(<RoadmapView roadmap={roadmap()} />);

    expect(screen.getByText("Please check these yourself")).toBeInTheDocument();
    expect(screen.getByText("Which edition of the book you use.")).toBeInTheDocument();
    expect(screen.getByText("What this plan assumes")).toBeInTheDocument();
    expect(screen.getByText("You already know Python.")).toBeInTheDocument();
  });

  it("leaves those boxes out when there is nothing to say", () => {
    render(<RoadmapView roadmap={roadmap({ unknowns: [], assumptions: [] })} />);

    expect(screen.queryByText("Please check these yourself")).not.toBeInTheDocument();
    expect(screen.queryByText("What this plan assumes")).not.toBeInTheDocument();
  });

  it("numbers the objectives and ties each topic to them", () => {
    render(<RoadmapView roadmap={roadmap()} />);

    expect(screen.getByText("Explain ownership")).toBeInTheDocument();
    expect(screen.getByText(/Supports objective 1(?! ·)/)).toBeInTheDocument();
    expect(screen.getByText(/Supports objectives 1, 2 · Needs: Ownership/)).toBeInTheDocument();
  });

  it("lists modules, topics, days, minutes and practice tasks", () => {
    render(<RoadmapView roadmap={roadmap()} />);

    expect(screen.getByRole("heading", { name: "Module 1: Core ideas" })).toBeInTheDocument();
    const borrowing = screen.getByRole("heading", { name: "Borrowing", level: 4 }).closest("li");
    expect(borrowing).not.toBeNull();
    expect(within(borrowing as HTMLElement).getByText("Day 2")).toBeInTheDocument();
    expect(within(borrowing as HTMLElement).getByText("30 min")).toBeInTheDocument();
    expect(within(borrowing as HTMLElement).getByText(/Practice:/)).toBeInTheDocument();
  });

  it("shows revision sessions with what they revisit, and optional extras as unscheduled", () => {
    render(<RoadmapView roadmap={roadmap()} />);

    expect(screen.getByText("Recall everything")).toBeInTheDocument();
    expect(screen.getByText("Revisits: Ownership, Borrowing")).toBeInTheDocument();
    expect(screen.getByText("Optional extras")).toBeInTheDocument();
    expect(screen.getByText(/not part of the study time/)).toBeInTheDocument();
    expect(screen.getByText("Read the compiler errors guide")).toBeInTheDocument();
  });

  it("lays the plan out day by day", () => {
    render(<RoadmapView roadmap={roadmap()} />);

    expect(screen.getByText(/Day-by-day schedule \(3 study days\)/)).toBeInTheDocument();
    expect(screen.getByText("Revise: Recall everything (20 min)")).toBeInTheDocument();
  });

  it("gives the headline numbers, from the server", () => {
    render(<RoadmapView roadmap={roadmap({ target_date: "2026-12-01" })} />);

    expect(screen.getByText("6")).toBeInTheDocument();
    expect(screen.getByText("4 h 20 min")).toBeInTheDocument();
    expect(screen.getByText("60 min / day")).toBeInTheDocument();
    expect(screen.getByText(/Target: 1 Dec 2026/)).toBeInTheDocument();
  });

  it("calls a test-provider plan a sample, and a real one nothing special", () => {
    const { rerender } = render(<RoadmapView roadmap={roadmap({ is_synthetic: true })} />);
    expect(screen.getByText(/built-in test provider, not an AI model/)).toBeInTheDocument();

    rerender(<RoadmapView roadmap={roadmap({ is_synthetic: false })} />);
    expect(screen.queryByText(/built-in test provider, not an AI model/)).not.toBeInTheDocument();
  });

  it("renders learner-written text as text, never as markup", () => {
    const hostile = '<img src=x onerror="alert(1)">';
    render(<RoadmapView roadmap={roadmap({ overview: hostile, assumptions: [hostile] })} />);

    expect(document.querySelector("img")).toBeNull();
    expect(screen.getAllByText(hostile).length).toBeGreaterThan(0);
  });
});

describe("VersionHistory", () => {
  const versions = [
    summary({ id: "v3", version: 3, status: "current", revision_feedback: "Fewer topics" }),
    summary({ id: "v2", version: 2, status: "superseded" }),
    summary({ id: "v1", version: 1, status: "superseded", is_synthetic: true }),
  ];

  it("lists every version, newest first, marking the current one and the one in view", () => {
    render(
      <VersionHistory
        goalId={GOAL}
        versions={versions}
        viewingId="v3"
        archived={false}
        timeZone="UTC"
      />,
    );

    const rows = screen.getAllByRole("listitem");
    expect(rows).toHaveLength(3);
    expect(within(rows[0] as HTMLElement).getByText("Version 3 (viewing)")).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(rows[0] as HTMLElement).getByText("Current")).toBeInTheDocument();
    expect(
      within(rows[0] as HTMLElement).getByText(/Asked for: “Fewer topics”/),
    ).toBeInTheDocument();
    expect(within(rows[2] as HTMLElement).getByText("Sample plan")).toBeInTheDocument();
  });

  it("links to other versions by number", () => {
    render(
      <VersionHistory
        goalId={GOAL}
        versions={versions}
        viewingId="v3"
        archived={false}
        timeZone="UTC"
      />,
    );

    expect(screen.getByRole("link", { name: "Version 2" })).toHaveAttribute(
      "href",
      `/goals/${GOAL}/roadmap?version=2`,
    );
  });

  it("lets an earlier version be made current, but not the current one", async () => {
    const user = userEvent.setup();
    render(
      <VersionHistory
        goalId={GOAL}
        versions={versions}
        viewingId="v3"
        archived={false}
        timeZone="UTC"
      />,
    );

    const buttons = screen.getAllByRole("button", { name: "Make current" });
    expect(buttons).toHaveLength(2);
    await user.click(buttons[0] as HTMLElement);

    await waitFor(() => expect(actions.makeRoadmapCurrentAction).toHaveBeenCalledTimes(1));
    expect(actions.makeRoadmapCurrentAction.mock.calls[0]?.slice(0, 2)).toEqual([GOAL, "v2"]);
  });

  it("offers no switching for an archived goal", () => {
    render(
      <VersionHistory goalId={GOAL} versions={versions} viewingId="v3" archived timeZone="UTC" />,
    );

    expect(screen.queryByRole("button", { name: "Make current" })).not.toBeInTheDocument();
  });
});
