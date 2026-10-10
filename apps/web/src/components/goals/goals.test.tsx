import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const actions = vi.hoisted(() => ({ createGoalAction: vi.fn() }));
vi.mock("@/lib/goals/actions", () => actions);

import { LoadError } from "@/components/feedback/load-error";
import { GoalCard, formatDate } from "@/components/goals/goal-card";
import { GoalForm } from "@/components/goals/goal-form";
import type { Goal } from "@/lib/api/server";

function goal(overrides: Partial<Goal> = {}): Goal {
  return {
    id: "11111111-1111-4111-8111-111111111111",
    title: "Learn Kubernetes",
    description: null,
    goal_type: "interview",
    current_level: "beginner",
    target_date: null,
    daily_minutes: 90,
    preferred_languages: ["en"],
    status: "active",
    created_at: "2026-10-09T00:00:00Z",
    updated_at: "2026-10-09T00:00:00Z",
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("GoalCard", () => {
  it("shows what the learner asked for, in plain words", () => {
    render(
      <GoalCard
        goal={goal({
          description: "For my backend interviews.",
          target_date: "2027-01-31",
          preferred_languages: ["en", "hi"],
        })}
      />,
    );

    expect(screen.getByText("Learn Kubernetes")).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
    expect(screen.getByText(/Interview preparation/)).toBeInTheDocument();
    expect(screen.getByText(/Level: Beginner/)).toBeInTheDocument();
    expect(screen.getByText("For my backend interviews.")).toBeInTheDocument();
    expect(screen.getByText("90 minutes a day")).toBeInTheDocument();
    expect(screen.getByText("By 31 Jan 2027")).toBeInTheDocument();
    expect(screen.getByText("English, Hindi (हिन्दी)")).toBeInTheDocument();
  });

  it("leaves out the date and description when the learner gave none", () => {
    render(<GoalCard goal={goal()} />);

    expect(screen.queryByText(/^By /)).not.toBeInTheDocument();
    expect(screen.queryByText("Target date")).not.toBeInTheDocument();
  });

  it.each([
    ["paused", "Paused"],
    ["completed", "Completed"],
    ["archived", "Archived"],
  ] as const)("labels a %s goal", (status, label) => {
    render(<GoalCard goal={goal({ status })} />);

    expect(screen.getByText(label)).toBeInTheDocument();
  });

  it("formats date-only values the same in every timezone", () => {
    expect(formatDate("2027-01-01")).toBe("1 Jan 2027");
    expect(formatDate("2026-12-31")).toBe("31 Dec 2026");
  });
});

describe("LoadError", () => {
  it("explains the failure and offers a way to retry", () => {
    render(
      <LoadError
        title="We couldn't load your goals"
        description="The learning service is temporarily unavailable. Your goals are safe."
        retryHref="/dashboard?cursor=abc"
        reference="req-123"
      />,
    );

    expect(screen.getByText("We couldn't load your goals")).toBeInTheDocument();
    expect(screen.getByText(/Your goals are safe/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Try again/ })).toHaveAttribute(
      "href",
      "/dashboard?cursor=abc",
    );
    expect(screen.getByText("req-123")).toBeInTheDocument();
  });

  it("omits the reference when there is none", () => {
    render(<LoadError title="Oops" description="Something went wrong." retryHref="/dashboard" />);

    expect(screen.queryByText(/Reference:/)).not.toBeInTheDocument();
  });
});

describe("GoalForm", () => {
  it("starts with sensible defaults that the learner can change", () => {
    render(<GoalForm />);

    expect(screen.getByLabelText("What do you want to learn?")).toHaveValue("");
    expect(screen.getByLabelText("Minutes you can study each day")).toHaveValue(60);
    expect(screen.getByLabelText("This goal is")).toHaveValue("professional_skill");
    // A level is never guessed for the learner.
    expect(screen.getByLabelText("Your level today")).toHaveValue("unknown");
    expect(screen.getByLabelText("English")).toBeChecked();
    expect(screen.getByLabelText(/Hindi/)).not.toBeChecked();
    expect(screen.getByRole("link", { name: "Cancel" })).toHaveAttribute("href", "/dashboard");
  });

  it("sends the choices, including every ticked language, and no owner", async () => {
    actions.createGoalAction.mockResolvedValue({ status: "idle" });
    const user = userEvent.setup();
    render(<GoalForm />);

    await user.type(screen.getByLabelText("What do you want to learn?"), "Learn Kubernetes");
    await user.selectOptions(screen.getByLabelText("This goal is"), "interview");
    await user.selectOptions(screen.getByLabelText("Your level today"), "beginner");
    await user.click(screen.getByLabelText(/Hindi/));
    await user.click(screen.getByRole("button", { name: "Create goal" }));

    await waitFor(() => expect(actions.createGoalAction).toHaveBeenCalledTimes(1));
    const data = actions.createGoalAction.mock.calls[0]?.[1] as FormData;
    expect(data.get("title")).toBe("Learn Kubernetes");
    expect(data.get("goalType")).toBe("interview");
    expect(data.get("currentLevel")).toBe("beginner");
    expect(data.getAll("languages")).toEqual(["en", "hi"]);
    expect([...data.keys()].filter((key) => /user|owner/i.test(key))).toEqual([]);
  });

  it("puts each server error next to its field and keeps what was typed", async () => {
    actions.createGoalAction.mockResolvedValue({
      status: "error",
      fieldErrors: {
        dailyMinutes: "Choose between 10 and 480 minutes.",
        languages: "Choose at least one language.",
      },
      values: {
        title: "Learn Kubernetes",
        description: "",
        goalType: "interview",
        currentLevel: "beginner",
        targetDate: "",
        dailyMinutes: "5",
        languages: [],
      },
    });
    const user = userEvent.setup();
    render(<GoalForm />);

    await user.type(screen.getByLabelText("What do you want to learn?"), "Learn Kubernetes");
    await user.click(screen.getByRole("button", { name: "Create goal" }));

    const minutesError = await screen.findByText("Choose between 10 and 480 minutes.");
    const minutes = screen.getByLabelText("Minutes you can study each day");
    expect(minutes).toHaveAttribute("aria-invalid", "true");
    expect(minutes.getAttribute("aria-describedby")).toContain(minutesError.id);
    expect(screen.getByText("Choose at least one language.")).toHaveAttribute("role", "alert");
    expect(screen.getByLabelText("What do you want to learn?")).toHaveValue("Learn Kubernetes");
    expect(screen.getByLabelText("This goal is")).toHaveValue("interview");
    expect(within(screen.getByRole("group")).getByLabelText("English")).not.toBeChecked();
  });

  it("shows a form-level failure, such as the goal limit", async () => {
    actions.createGoalAction.mockResolvedValue({
      status: "error",
      formError: "You can have up to 50 goals at once.",
      fieldErrors: {},
      values: {
        title: "One more",
        description: "",
        goalType: "general",
        currentLevel: "unknown",
        targetDate: "",
        dailyMinutes: "60",
        languages: ["en"],
      },
    });
    const user = userEvent.setup();
    render(<GoalForm />);

    await user.type(screen.getByLabelText("What do you want to learn?"), "One more");
    await user.click(screen.getByRole("button", { name: "Create goal" }));

    expect(await screen.findByText("You can have up to 50 goals at once.")).toBeInTheDocument();
  });
});
