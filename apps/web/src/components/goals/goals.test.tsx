import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { LoadError } from "@/components/feedback/load-error";
import { GoalCard, formatDate } from "@/components/goals/goal-card";
import { GoalDetails } from "@/components/goals/goal-details";
import { GoalForm } from "@/components/goals/goal-form";
import { GoalList } from "@/components/goals/goal-list";
import type { Goal } from "@/lib/api/server";
import { newGoalDefaults, type GoalFormState } from "@/lib/goals/schema";

const GOAL_ID = "11111111-1111-4111-8111-111111111111";

function goal(overrides: Partial<Goal> = {}): Goal {
  return {
    id: GOAL_ID,
    title: "Learn Kubernetes",
    description: null,
    goal_type: "interview",
    current_level: "beginner",
    target_date: null,
    daily_minutes: 90,
    preferred_languages: ["en"],
    learning_preferences: ["examples", "quizzes", "revision"],
    status: "active",
    completed_at: null,
    archived_at: null,
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

  it("links to the goal's own page", () => {
    render(<GoalCard goal={goal()} />);

    expect(screen.getByRole("link", { name: "Learn Kubernetes" })).toHaveAttribute(
      "href",
      `/goals/${GOAL_ID}`,
    );
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

describe("GoalList", () => {
  it("lists the goals under an accessible name", () => {
    render(
      <GoalList
        label="Goals in progress"
        goals={[goal(), goal({ id: "22222222-2222-4222-8222-222222222222", title: "Learn Rust" })]}
      />,
    );

    const list = screen.getByRole("list", { name: "Goals in progress" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(2);
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument(); // one page: no paging links
  });

  it("offers older and newest links when there is more", () => {
    render(
      <GoalList
        label="Completed goals"
        goals={[goal()]}
        nextHref="/dashboard?completed_cursor=abc"
        firstHref="/dashboard"
      />,
    );

    expect(screen.getByRole("link", { name: "Show older" })).toHaveAttribute(
      "href",
      "/dashboard?completed_cursor=abc",
    );
    expect(screen.getByRole("link", { name: "Back to newest" })).toHaveAttribute(
      "href",
      "/dashboard",
    );
  });
});

describe("GoalDetails", () => {
  it("shows everything the learner told us", () => {
    render(
      <GoalDetails
        goal={goal({
          description: "Notes about my plan",
          target_date: "2027-01-31",
          preferred_languages: ["en", "or"],
          learning_preferences: ["quizzes", "revision"],
        })}
        timeZone="Asia/Kolkata"
        daysToTarget={113}
      />,
    );

    expect(screen.getByText("Notes about my plan")).toBeInTheDocument();
    expect(screen.getByText("Interview preparation")).toBeInTheDocument();
    expect(screen.getByText("Beginner")).toBeInTheDocument();
    expect(screen.getByText("90 minutes")).toBeInTheDocument();
    expect(screen.getByText(/31 Jan 2027/)).toBeInTheDocument();
    expect(screen.getByText(/in 113 days/)).toBeInTheDocument();
    expect(screen.getByText("English, Odia (ଓଡ଼ିଆ)")).toBeInTheDocument();
    expect(screen.getByText("Practice quizzes")).toBeInTheDocument();
    expect(screen.getByText("Spaced revision")).toBeInTheDocument();
    expect(screen.queryByText("Worked examples")).not.toBeInTheDocument();
  });

  it("says plainly when there is no deadline and no extras", () => {
    render(
      <GoalDetails goal={goal({ learning_preferences: [] })} timeZone="UTC" daysToTarget={null} />,
    );

    expect(screen.getByText("No deadline")).toBeInTheDocument();
    expect(screen.getByText("No extras selected")).toBeInTheDocument();
  });

  it("points out a target date that has passed, unless the goal is done", () => {
    const { rerender } = render(
      <GoalDetails goal={goal({ target_date: "2026-01-01" })} timeZone="UTC" daysToTarget={-9} />,
    );
    expect(screen.getByText(/passed 9 days ago/)).toBeInTheDocument();

    rerender(
      <GoalDetails
        goal={goal({ target_date: "2026-01-01", status: "completed" })}
        timeZone="UTC"
        daysToTarget={-9}
      />,
    );
    expect(screen.queryByText(/passed/)).not.toBeInTheDocument();
  });

  it("shows when it was created, and completed, in the learner's timezone", () => {
    render(
      <GoalDetails
        goal={goal({
          status: "completed",
          created_at: "2026-10-09T20:00:00Z", // 10 Oct, 01:30 in Kolkata
          completed_at: "2026-10-10T20:00:00Z",
        })}
        timeZone="Asia/Kolkata"
        daysToTarget={null}
      />,
    );

    expect(screen.getByText("10 Oct 2026")).toBeInTheDocument(); // created, already the next day
    expect(screen.getByText("11 Oct 2026")).toBeInTheDocument(); // completed
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
  const save = vi.fn<(state: GoalFormState, formData: FormData) => Promise<GoalFormState>>();
  const defaults = newGoalDefaults();

  function renderForm(overrides: Partial<typeof defaults> = {}) {
    return render(
      <GoalForm
        action={save}
        defaults={{ ...defaults, ...overrides }}
        submitLabel="Create goal"
        cancelHref="/dashboard"
      />,
    );
  }

  beforeEach(() => {
    save.mockReset();
  });

  it("starts with sensible defaults that the learner can change", () => {
    renderForm();

    expect(screen.getByLabelText("What do you want to learn?")).toHaveValue("");
    expect(screen.getByLabelText("Minutes you can study each day")).toHaveValue(60);
    expect(screen.getByLabelText("This goal is")).toHaveValue("professional_skill");
    // A level is never guessed for the learner.
    expect(screen.getByLabelText("Your level today")).toHaveValue("unknown");
    expect(screen.getByLabelText("English")).toBeChecked();
    expect(screen.getByLabelText(/Hindi/)).not.toBeChecked();
    expect(screen.getByLabelText("Worked examples")).toBeChecked();
    expect(screen.getByLabelText("Practice quizzes")).toBeChecked();
    expect(screen.getByLabelText("Spaced revision")).toBeChecked();
    expect(screen.getByRole("link", { name: "Cancel" })).toHaveAttribute("href", "/dashboard");
  });

  it("does not insist on a target date", () => {
    renderForm();

    expect(screen.getByLabelText(/Target date/)).not.toBeRequired();
  });

  it("uses the label and cancel link it is given", () => {
    render(
      <GoalForm
        action={save}
        defaults={defaults}
        submitLabel="Save changes"
        cancelHref={`/goals/${GOAL_ID}`}
      />,
    );

    expect(screen.getByRole("button", { name: "Save changes" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Cancel" })).toHaveAttribute(
      "href",
      `/goals/${GOAL_ID}`,
    );
  });

  it("starts an edit from the goal's own values", () => {
    renderForm({
      title: "Pass the CKA exam",
      goalType: "exam",
      currentLevel: "advanced",
      targetDate: "2027-03-01",
      dailyMinutes: "30",
      languages: ["hi"],
      learningPreferences: ["revision"],
    });

    expect(screen.getByLabelText("What do you want to learn?")).toHaveValue("Pass the CKA exam");
    expect(screen.getByLabelText("This goal is")).toHaveValue("exam");
    expect(screen.getByLabelText("Your level today")).toHaveValue("advanced");
    expect(screen.getByLabelText(/Target date/)).toHaveValue("2027-03-01");
    expect(screen.getByLabelText("Minutes you can study each day")).toHaveValue(30);
    expect(screen.getByLabelText("English")).not.toBeChecked();
    expect(screen.getByLabelText(/Hindi/)).toBeChecked();
    expect(screen.getByLabelText("Worked examples")).not.toBeChecked();
    expect(screen.getByLabelText("Spaced revision")).toBeChecked();
  });

  it("sends the choices, including every ticked box, and no owner", async () => {
    save.mockResolvedValue({ status: "idle" });
    const user = userEvent.setup();
    renderForm();

    await user.type(screen.getByLabelText("What do you want to learn?"), "Learn Kubernetes");
    await user.selectOptions(screen.getByLabelText("This goal is"), "interview");
    await user.selectOptions(screen.getByLabelText("Your level today"), "beginner");
    await user.click(screen.getByLabelText(/Hindi/));
    await user.click(screen.getByLabelText("Practice quizzes")); // untick
    await user.click(screen.getByRole("button", { name: "Create goal" }));

    await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
    const data = save.mock.calls[0]?.[1] as FormData;
    expect(data.get("title")).toBe("Learn Kubernetes");
    expect(data.get("goalType")).toBe("interview");
    expect(data.get("currentLevel")).toBe("beginner");
    expect(data.getAll("languages")).toEqual(["en", "hi"]);
    expect(data.getAll("learningPreferences")).toEqual(["examples", "revision"]);
    expect([...data.keys()].filter((key) => /user|owner/i.test(key))).toEqual([]);
  });

  it("puts each server error next to its field and keeps what was typed", async () => {
    save.mockResolvedValue({
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
        learningPreferences: ["revision"],
      },
    });
    const user = userEvent.setup();
    renderForm();

    await user.type(screen.getByLabelText("What do you want to learn?"), "Learn Kubernetes");
    await user.click(screen.getByRole("button", { name: "Create goal" }));

    const minutesError = await screen.findByText("Choose between 10 and 480 minutes.");
    const minutes = screen.getByLabelText("Minutes you can study each day");
    expect(minutes).toHaveAttribute("aria-invalid", "true");
    expect(minutes.getAttribute("aria-describedby")).toContain(minutesError.id);
    expect(screen.getByText("Choose at least one language.")).toHaveAttribute("role", "alert");
    expect(screen.getByLabelText("What do you want to learn?")).toHaveValue("Learn Kubernetes");
    expect(screen.getByLabelText("This goal is")).toHaveValue("interview");
    expect(screen.getByLabelText("Your level today")).toHaveValue("beginner");
    const languages = screen.getByRole("group", { name: /Languages/ });
    expect(within(languages).getByLabelText("English")).not.toBeChecked();
    const style = screen.getByRole("group", { name: /How you like to learn/ });
    expect(within(style).getByLabelText("Worked examples")).not.toBeChecked();
    expect(within(style).getByLabelText("Spaced revision")).toBeChecked();
  });

  it("shows a form-level failure, such as the goal limit", async () => {
    save.mockResolvedValue({
      status: "error",
      formError: "You can have up to 50 goals at once.",
      fieldErrors: {},
      values: { ...defaults, title: "One more" },
    });
    const user = userEvent.setup();
    renderForm();

    await user.type(screen.getByLabelText("What do you want to learn?"), "One more");
    await user.click(screen.getByRole("button", { name: "Create goal" }));

    expect(await screen.findByText("You can have up to 50 goals at once.")).toBeInTheDocument();
  });
});
