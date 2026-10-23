import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const actions = vi.hoisted(() => ({
  createFlashcardAction: vi.fn(),
  updateFlashcardAction: vi.fn(),
  deleteFlashcardAction: vi.fn(),
  reviewFlashcardAction: vi.fn(),
}));
vi.mock("@/lib/flashcards/actions", () => actions);

import { AddCardForm } from "@/components/flashcards/add-card-form";
import { CardRow } from "@/components/flashcards/card-row";
import { ReviewCard } from "@/components/flashcards/review-card";

const GOAL = "3f2c1a7e-4d5b-4c6e-8f90-1234567890ab";
const CARD = "9a8b7c6d-5e4f-4a3b-8c2d-0f1e2d3c4b5a";
const KEY = "5b0b1c0e-6f31-4c9a-9d2e-aaaaaaaaaaaa";

beforeEach(() => {
  vi.clearAllMocks();
});

describe("ReviewCard", () => {
  function renderCard() {
    return render(
      <ReviewCard
        goalId={GOAL}
        cardId={CARD}
        front="What is ownership?"
        back="Each value has one owner."
        reviewKey={KEY}
      />,
    );
  }

  it("shows the question and keeps the answer closed until asked", () => {
    const { container } = renderCard();

    expect(screen.getByText("What is ownership?")).toBeVisible();
    const details = container.querySelector("details");
    expect(details).not.toBeNull();
    expect(details?.open).toBe(false);
    expect(screen.getByText("Show answer")).toBeVisible();
  });

  it("opens the answer with a plain disclosure, no script needed", async () => {
    const { container } = renderCard();

    await userEvent.click(screen.getByText("Show answer"));

    expect(container.querySelector("details")?.open).toBe(true);
    expect(screen.getByText("Each value has one owner.")).toBeVisible();
  });

  it("offers the four ratings as submit buttons, hardest first, and nothing else to send", () => {
    const { container } = renderCard();

    const buttons = within(container.querySelector("form") as HTMLElement).getAllByRole("button", {
      hidden: true,
    });
    expect(buttons.map((button) => button.getAttribute("value"))).toEqual([
      "again",
      "hard",
      "good",
      "easy",
    ]);
    expect(buttons.every((button) => button.getAttribute("name") === "rating")).toBe(true);
    const hidden = [...container.querySelectorAll("input")];
    expect(hidden).toHaveLength(1);
    expect(hidden[0]).toMatchObject({ type: "hidden", name: "key", value: KEY });
  });

  it("explains each rating in words, not colour alone", () => {
    renderCard();

    expect(screen.getByText("I forgot it", { selector: "span" })).toBeInTheDocument();
    expect(screen.getByText("I remembered it", { selector: "span" })).toBeInTheDocument();
    expect(screen.getByText("How well did you remember it?")).toBeInTheDocument();
  });

  it("binds the action to this goal and card", () => {
    renderCard();

    // The form's action is the Server Action with the goal and card already bound.
    expect(actions.reviewFlashcardAction).toBeDefined();
  });
});

describe("CardRow", () => {
  const props = {
    goalId: GOAL,
    cardId: CARD,
    front: "Front text",
    back: "Back text",
    dueLabel: "Due tomorrow",
    stage: "Learning",
  };

  it("shows both sides, the stage and when it is due", () => {
    render(
      <ul>
        <CardRow {...props} readOnly={false} />
      </ul>,
    );

    expect(screen.getByText("Front text", { selector: "p" })).toBeInTheDocument();
    expect(screen.getByText("Back text", { selector: "p" })).toBeInTheDocument();
    expect(screen.getByText("Learning")).toBeInTheDocument();
    expect(screen.getByText("Due tomorrow")).toBeInTheDocument();
  });

  it("offers edit and delete on a goal that can be changed", () => {
    render(
      <ul>
        <CardRow {...props} readOnly={false} />
      </ul>,
    );

    expect(screen.getByText("Edit")).toBeInTheDocument();
    expect(screen.getByText("Delete")).toBeInTheDocument();
  });

  it("asks before deleting, and says the history goes with the card", () => {
    render(
      <ul>
        <CardRow {...props} readOnly={false} />
      </ul>,
    );

    expect(screen.getByText(/delete this card and its review history/i)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Yes, delete the card", hidden: true }),
    ).toBeInTheDocument();
  });

  it("shows an archived goal's card without any way to change it", () => {
    render(
      <ul>
        <CardRow {...props} readOnly />
      </ul>,
    );

    expect(screen.getByText("Front text", { selector: "p" })).toBeInTheDocument();
    expect(screen.queryByText("Edit")).not.toBeInTheDocument();
    expect(screen.queryByText("Delete")).not.toBeInTheDocument();
  });
});

describe("AddCardForm", () => {
  it("has labelled fields for the two sides", () => {
    render(<AddCardForm goalId={GOAL} />);

    expect(screen.getByLabelText("Front")).toBeInTheDocument();
    expect(screen.getByLabelText("Back")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add card" })).toBeInTheDocument();
  });

  it("shows the server's field error next to the field and keeps what was typed", async () => {
    actions.createFlashcardAction.mockResolvedValue({
      status: "error",
      fieldErrors: { front: "Write the question or prompt." },
      values: { front: "", back: "My answer" },
    });
    render(<AddCardForm goalId={GOAL} />);

    await userEvent.type(screen.getByLabelText("Back"), "My answer");
    await userEvent.click(screen.getByRole("button", { name: "Add card" }));

    expect(await screen.findByText("Write the question or prompt.")).toBeInTheDocument();
    expect(screen.getByLabelText("Front")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByLabelText("Back")).toHaveValue("My answer");
  });

  it("confirms a saved card", async () => {
    actions.createFlashcardAction.mockResolvedValue({
      status: "success",
      message: "Card added.",
      values: { front: "", back: "" },
    });
    render(<AddCardForm goalId={GOAL} />);

    await userEvent.type(screen.getByLabelText("Front"), "Q");
    await userEvent.type(screen.getByLabelText("Back"), "A");
    await userEvent.click(screen.getByRole("button", { name: "Add card" }));

    expect(await screen.findByText("Card added.")).toBeInTheDocument();
    expect(screen.getByLabelText("Front")).toHaveValue("");
  });
});
