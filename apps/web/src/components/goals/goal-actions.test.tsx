import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const actions = vi.hoisted(() => ({
  changeGoalStatusAction: vi.fn(),
  deleteGoalAction: vi.fn(),
}));
vi.mock("@/lib/goals/actions", () => actions);

import { GoalActions } from "@/components/goals/goal-actions";

const GOAL_ID = "11111111-1111-4111-8111-111111111111";

const buttonNames = () => screen.getAllByRole("button").map((button) => button.textContent?.trim());

beforeEach(() => {
  vi.clearAllMocks();
  actions.changeGoalStatusAction.mockResolvedValue(undefined);
  actions.deleteGoalAction.mockResolvedValue(undefined);
});

describe("GoalActions offers what the current state allows", () => {
  it("active: edit, pause, complete, archive", () => {
    render(<GoalActions goalId={GOAL_ID} status="active" />);

    expect(screen.getByRole("link", { name: "Edit" })).toHaveAttribute(
      "href",
      `/goals/${GOAL_ID}/edit`,
    );
    expect(buttonNames()).toEqual(["Pause", "Mark complete", "Archive"]);
  });

  it("paused: edit, resume, complete, archive", () => {
    render(<GoalActions goalId={GOAL_ID} status="paused" />);

    expect(screen.getByRole("link", { name: "Edit" })).toBeInTheDocument();
    expect(buttonNames()).toEqual(["Resume", "Mark complete", "Archive"]);
  });

  it("completed: edit, reopen, archive", () => {
    render(<GoalActions goalId={GOAL_ID} status="completed" />);

    expect(screen.getByRole("link", { name: "Edit" })).toBeInTheDocument();
    expect(buttonNames()).toEqual(["Reopen", "Archive"]);
  });

  it("archived: restore or delete, and no way to edit", () => {
    render(<GoalActions goalId={GOAL_ID} status="archived" />);

    expect(screen.queryByRole("link", { name: "Edit" })).not.toBeInTheDocument();
    expect(buttonNames()).toEqual(["Restore", "Delete permanently"]);
  });
});

describe("moving a goal", () => {
  it.each([
    ["active", "Pause", "paused"],
    ["paused", "Resume", "active"],
    ["active", "Mark complete", "completed"],
    ["completed", "Reopen", "active"],
    ["archived", "Restore", "active"],
  ] as const)("%s goal: '%s' asks for status %s", async (status, label, target) => {
    const user = userEvent.setup();
    render(<GoalActions goalId={GOAL_ID} status={status} />);

    await user.click(screen.getByRole("button", { name: label }));

    await waitFor(() => expect(actions.changeGoalStatusAction).toHaveBeenCalledTimes(1));
    const [goalId, requested] = actions.changeGoalStatusAction.mock.calls[0] ?? [];
    expect([goalId, requested]).toEqual([GOAL_ID, target]);
  });
});

describe("destructive actions ask first", () => {
  it("archiving needs a confirmation, and cancelling does nothing", async () => {
    const user = userEvent.setup();
    render(<GoalActions goalId={GOAL_ID} status="active" />);

    await user.click(screen.getByRole("button", { name: "Archive" }));
    const dialog = await screen.findByRole("dialog", { name: "Archive this goal?" });
    expect(within(dialog).getByText(/restore it from the archive/)).toBeInTheDocument();
    expect(actions.changeGoalStatusAction).not.toHaveBeenCalled();

    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(actions.changeGoalStatusAction).not.toHaveBeenCalled();
  });

  it("confirming archives the goal", async () => {
    const user = userEvent.setup();
    render(<GoalActions goalId={GOAL_ID} status="paused" />);

    await user.click(screen.getByRole("button", { name: "Archive" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Archive goal" }));

    await waitFor(() => expect(actions.changeGoalStatusAction).toHaveBeenCalledTimes(1));
    const [goalId, requested] = actions.changeGoalStatusAction.mock.calls[0] ?? [];
    expect([goalId, requested]).toEqual([GOAL_ID, "archived"]);
  });

  it("deleting says it is permanent, and nothing is deleted until confirmed", async () => {
    const user = userEvent.setup();
    render(<GoalActions goalId={GOAL_ID} status="archived" />);

    await user.click(screen.getByRole("button", { name: "Delete permanently" }));
    const dialog = await screen.findByRole("dialog", { name: "Delete this goal permanently?" });
    expect(within(dialog).getByText(/cannot be undone/)).toBeInTheDocument();
    expect(actions.deleteGoalAction).not.toHaveBeenCalled();

    await user.click(within(dialog).getByRole("button", { name: "Delete forever" }));

    await waitFor(() => expect(actions.deleteGoalAction).toHaveBeenCalledTimes(1));
    expect(actions.deleteGoalAction.mock.calls[0]?.[0]).toBe(GOAL_ID);
  });

  it("closing the delete dialog with Escape deletes nothing", async () => {
    const user = userEvent.setup();
    render(<GoalActions goalId={GOAL_ID} status="archived" />);

    await user.click(screen.getByRole("button", { name: "Delete permanently" }));
    await screen.findByRole("dialog");
    await user.keyboard("{Escape}");

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(actions.deleteGoalAction).not.toHaveBeenCalled();
  });
});
