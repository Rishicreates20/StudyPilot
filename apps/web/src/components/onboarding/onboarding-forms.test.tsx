import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const actions = vi.hoisted(() => ({
  saveAboutYouAction: vi.fn(),
  saveStudyStyleAction: vi.fn(),
  createFirstGoalAction: vi.fn(),
  skipOnboardingAction: vi.fn(),
}));
vi.mock("@/lib/onboarding/actions", () => actions);

import {
  AboutYouForm,
  FirstGoalForm,
  SkipOnboardingButton,
  StudyStyleForm,
} from "@/components/onboarding/onboarding-forms";
import { newGoalDefaults } from "@/lib/goals/schema";
import type { SettingsValues } from "@/lib/profile/schema";

const saved: SettingsValues = {
  displayName: "",
  timezone: "Asia/Kolkata",
  dailyMinutes: "60",
  languages: ["en"],
  learningPreferences: ["examples", "quizzes", "revision"],
};

const submitted = (mock: ReturnType<typeof vi.fn>): FormData => mock.mock.calls[0]?.[1] as FormData;

beforeEach(() => {
  vi.clearAllMocks();
});

describe("step 1: about you", () => {
  it("asks for a name (optional) and the languages, nothing more", () => {
    render(<AboutYouForm defaults={saved} />);

    expect(screen.getByLabelText(/What should we call you/)).not.toBeRequired();
    expect(screen.getByLabelText("English")).toBeChecked();
    expect(screen.queryByLabelText(/minutes/i)).not.toBeInTheDocument();
  });

  it("starts from what was saved on an earlier visit", () => {
    render(<AboutYouForm defaults={{ ...saved, displayName: "Ada", languages: ["hi", "or"] }} />);

    expect(screen.getByLabelText(/What should we call you/)).toHaveValue("Ada");
    expect(screen.getByLabelText("English")).not.toBeChecked();
    expect(screen.getByLabelText(/Hindi/)).toBeChecked();
  });

  it("can continue without a name", async () => {
    actions.saveAboutYouAction.mockResolvedValue({ status: "idle" });
    const user = userEvent.setup();
    render(<AboutYouForm defaults={saved} />);

    await user.click(screen.getByRole("button", { name: "Continue" }));

    await waitFor(() => expect(actions.saveAboutYouAction).toHaveBeenCalledTimes(1));
    const data = submitted(actions.saveAboutYouAction);
    expect(data.get("displayName")).toBe("");
    expect(data.getAll("languages")).toEqual(["en"]);
  });

  it("shows what is wrong and keeps the answers", async () => {
    actions.saveAboutYouAction.mockResolvedValue({
      status: "error",
      fieldErrors: { languages: "Choose at least one language." },
      values: { ...saved, displayName: "Ada", languages: [] },
    });
    const user = userEvent.setup();
    render(<AboutYouForm defaults={saved} />);

    await user.type(screen.getByLabelText(/What should we call you/), "Ada");
    await user.click(screen.getByLabelText("English")); // untick
    await user.click(screen.getByRole("button", { name: "Continue" }));

    expect(await screen.findByText("Choose at least one language.")).toBeInTheDocument();
    expect(screen.getByLabelText(/What should we call you/)).toHaveValue("Ada");
  });
});

describe("step 2: how you like to study", () => {
  it("asks for daily minutes and kinds of practice, and can go back", () => {
    render(<StudyStyleForm defaults={saved} />);

    expect(screen.getByLabelText(/How many minutes can you study/)).toHaveValue(60);
    expect(screen.getByLabelText("Worked examples")).toBeChecked();
    expect(screen.getByRole("link", { name: "Back" })).toHaveAttribute(
      "href",
      "/onboarding?step=1",
    );
  });

  it("sends the answers, including an empty choice of practice", async () => {
    actions.saveStudyStyleAction.mockResolvedValue({ status: "idle" });
    const user = userEvent.setup();
    render(<StudyStyleForm defaults={saved} />);

    const minutes = screen.getByLabelText(/How many minutes can you study/);
    await user.clear(minutes);
    await user.type(minutes, "45");
    for (const label of ["Worked examples", "Practice quizzes", "Spaced revision"]) {
      await user.click(screen.getByLabelText(label));
    }
    await user.click(screen.getByRole("button", { name: "Continue" }));

    await waitFor(() => expect(actions.saveStudyStyleAction).toHaveBeenCalledTimes(1));
    const data = submitted(actions.saveStudyStyleAction);
    expect(data.get("dailyMinutes")).toBe("45");
    expect(data.getAll("learningPreferences")).toEqual([]);
  });
});

describe("step 3: the first goal", () => {
  it("asks only for the essentials: no time, languages or practice, and no required date", () => {
    render(<FirstGoalForm defaults={newGoalDefaults()} />);

    expect(screen.getByLabelText("What do you want to learn?")).toBeRequired();
    expect(screen.getByLabelText(/Target date/)).not.toBeRequired();
    expect(screen.queryByLabelText(/minutes you can study/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("group", { name: /Languages/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("group", { name: /How you like to learn/ })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back" })).toHaveAttribute(
      "href",
      "/onboarding?step=2",
    );
  });

  it("creates the goal with just a title", async () => {
    actions.createFirstGoalAction.mockResolvedValue({ status: "idle" });
    const user = userEvent.setup();
    render(<FirstGoalForm defaults={newGoalDefaults()} />);

    await user.type(screen.getByLabelText("What do you want to learn?"), "Learn Docker");
    await user.click(screen.getByRole("button", { name: "Create my first goal" }));

    await waitFor(() => expect(actions.createFirstGoalAction).toHaveBeenCalledTimes(1));
    const data = submitted(actions.createFirstGoalAction);
    expect(data.get("title")).toBe("Learn Docker");
    expect(data.get("targetDate")).toBe("");
    expect([...data.keys()]).not.toContain("user_id");
  });

  it("shows a failure and keeps the title", async () => {
    actions.createFirstGoalAction.mockResolvedValue({
      status: "error",
      formError: "We can't reach the learning service right now. Your goal was not saved.",
      fieldErrors: {},
      values: { ...newGoalDefaults(), title: "Learn Docker" },
    });
    const user = userEvent.setup();
    render(<FirstGoalForm defaults={newGoalDefaults()} />);

    await user.type(screen.getByLabelText("What do you want to learn?"), "Learn Docker");
    await user.click(screen.getByRole("button", { name: "Create my first goal" }));

    expect(await screen.findByText(/was not saved/)).toBeInTheDocument();
    expect(screen.getByLabelText("What do you want to learn?")).toHaveValue("Learn Docker");
  });
});

describe("skipping", () => {
  it("is always available and runs its own action", async () => {
    actions.skipOnboardingAction.mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<SkipOnboardingButton />);

    await user.click(screen.getByRole("button", { name: "Skip for now" }));

    await waitFor(() => expect(actions.skipOnboardingAction).toHaveBeenCalledTimes(1));
  });
});
