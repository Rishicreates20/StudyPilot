import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { InboxIcon } from "lucide-react";
import { describe, expect, it, vi } from "vitest";

import { EmptyState } from "@/components/feedback/empty-state";
import { ErrorState } from "@/components/feedback/error-state";
import { CardGridSkeleton, LoadingState } from "@/components/feedback/loading-state";

describe("EmptyState", () => {
  it("explains the situation and offers a next step", () => {
    render(
      <EmptyState
        icon={InboxIcon}
        title="No goals yet"
        description="Create your first goal."
        action={<button type="button">Create goal</button>}
      />,
    );

    expect(screen.getByRole("heading", { name: "No goals yet" })).toBeInTheDocument();
    expect(screen.getByText("Create your first goal.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create goal" })).toBeInTheDocument();
  });

  it("lets the caller choose the heading level", () => {
    render(<EmptyState title="Nothing here" headingLevel="h2" />);

    expect(screen.getByRole("heading", { level: 2, name: "Nothing here" })).toBeInTheDocument();
  });
});

describe("LoadingState", () => {
  it("announces what is loading", () => {
    render(<LoadingState label="Generating your roadmap" />);

    expect(screen.getByRole("status")).toHaveTextContent("Generating your roadmap");
  });

  it("announces skeleton placeholders once, not block by block", () => {
    render(<CardGridSkeleton count={3} label="Loading goals" />);

    const region = screen.getByRole("status");
    expect(region).toHaveAttribute("aria-busy", "true");
    expect(region).toHaveTextContent("Loading goals");
  });
});

describe("ErrorState", () => {
  it("shows the message as an alert with a reference to quote", () => {
    render(<ErrorState title="Couldn't load goals" description="Try again." reference="req-123" />);

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Couldn't load goals");
    expect(alert).toHaveTextContent("req-123");
  });

  it("offers a retry only when a handler is provided", async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    const { rerender } = render(<ErrorState />);

    expect(screen.queryByRole("button", { name: /try again/i })).not.toBeInTheDocument();

    rerender(<ErrorState onRetry={onRetry} />);
    await user.click(screen.getByRole("button", { name: /try again/i }));

    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});
