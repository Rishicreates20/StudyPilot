// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest";

const session = vi.hoisted(() => ({
  getSessionUser: vi.fn(),
  getAccessToken: vi.fn(),
}));
const api = vi.hoisted(() => ({
  createFlashcard: vi.fn(),
  updateFlashcard: vi.fn(),
  deleteFlashcard: vi.fn(),
  reviewFlashcard: vi.fn(),
}));
const cache = vi.hoisted(() => ({ revalidatePath: vi.fn() }));

vi.mock("next/cache", () => cache);
vi.mock("next/navigation", () => ({
  redirect: (url: string) => {
    throw new Error(`REDIRECT:${url}`);
  },
  notFound: () => {
    throw new Error("NOT_FOUND");
  },
}));
vi.mock("@/lib/auth/session", () => session);
vi.mock("@/lib/api/server", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/server")>()),
  ...api,
}));

import { ApiError } from "@/lib/api/server";
import {
  createFlashcardAction,
  deleteFlashcardAction,
  reviewFlashcardAction,
  updateFlashcardAction,
} from "@/lib/flashcards/actions";

const GOAL = "3f2c1a7e-4d5b-4c6e-8f90-1234567890ab";
const CARD = "9a8b7c6d-5e4f-4a3b-8c2d-0f1e2d3c4b5a";
const KEY = "5b0b1c0e-6f31-4c9a-9d2e-aaaaaaaaaaaa";
const DECK = `/goals/${GOAL}/flashcards`;
const REVIEW = `${DECK}/review`;
const IDLE = { status: "idle" } as const;

function form(fields: Record<string, string>): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(fields)) data.append(key, value);
  return data;
}

beforeEach(() => {
  vi.clearAllMocks();
  session.getSessionUser.mockResolvedValue({ id: "u1", email: "a@b.c" });
  session.getAccessToken.mockResolvedValue("access-token-123");
});

describe("createFlashcardAction", () => {
  it("creates the card with the caller's token and sends only the two sides", async () => {
    api.createFlashcard.mockResolvedValue({ id: CARD });

    const state = await createFlashcardAction(
      GOAL,
      IDLE,
      form({ front: " Q ", back: " A ", user_id: "someone-else", due_at: "2030-01-01" }),
    );

    expect(api.createFlashcard).toHaveBeenCalledWith("access-token-123", GOAL, {
      front: "Q",
      back: "A",
    });
    expect(cache.revalidatePath).toHaveBeenCalledWith(DECK);
    expect(state).toEqual({
      status: "success",
      message: "Card added.",
      values: { front: "", back: "" },
    });
  });

  it("checks the fields before calling the API and keeps what was typed", async () => {
    const state = await createFlashcardAction(GOAL, IDLE, form({ front: "", back: "Answer" }));

    expect(api.createFlashcard).not.toHaveBeenCalled();
    expect(state).toMatchObject({
      status: "error",
      fieldErrors: { front: "Write the question or prompt." },
      values: { front: "", back: "Answer" },
    });
  });

  it("shows the API's own sentence for a full deck and keeps what was typed", async () => {
    api.createFlashcard.mockRejectedValue(
      new ApiError(409, "FLASHCARD_LIMIT_REACHED", "A goal can have at most 500 flashcards."),
    );

    const state = await createFlashcardAction(GOAL, IDLE, form({ front: "Q", back: "A" }));

    expect(state).toMatchObject({
      status: "error",
      formError: "A goal can have at most 500 flashcards.",
      values: { front: "Q", back: "A" },
    });
  });

  it("says nothing was saved when the service is down", async () => {
    api.createFlashcard.mockRejectedValue(new ApiError(0, "API_UNREACHABLE", "down"));

    const state = await createFlashcardAction(GOAL, IDLE, form({ front: "Q", back: "A" }));

    expect(state).toMatchObject({
      status: "error",
      formError: expect.stringMatching(/nothing was saved/),
    });
  });

  it("sends a missing or someone else's goal to the not-found page", async () => {
    api.createFlashcard.mockRejectedValue(new ApiError(404, "GOAL_NOT_FOUND", "no"));

    await expect(
      createFlashcardAction(GOAL, IDLE, form({ front: "Q", back: "A" })),
    ).rejects.toThrow("NOT_FOUND");
  });

  it("sends an ended session to sign-in with the marker that shows the form", async () => {
    api.createFlashcard.mockRejectedValue(new ApiError(401, "UNAUTHENTICATED", "no"));

    await expect(
      createFlashcardAction(GOAL, IDLE, form({ front: "Q", back: "A" })),
    ).rejects.toThrow(/REDIRECT:\/sign-in\?.*ended/);
  });

  it("refuses a goal id that is not an id, before anything is called", async () => {
    await expect(
      createFlashcardAction("../me", IDLE, form({ front: "Q", back: "A" })),
    ).rejects.toThrow("NOT_FOUND");

    expect(api.createFlashcard).not.toHaveBeenCalled();
  });
});

describe("updateFlashcardAction", () => {
  it("saves the two sides and reports it", async () => {
    api.updateFlashcard.mockResolvedValue({ id: CARD });

    const state = await updateFlashcardAction(
      GOAL,
      CARD,
      IDLE,
      form({ front: "New Q", back: "New A" }),
    );

    expect(api.updateFlashcard).toHaveBeenCalledWith("access-token-123", CARD, {
      front: "New Q",
      back: "New A",
    });
    expect(state).toMatchObject({ status: "success", values: { front: "New Q", back: "New A" } });
  });

  it("refuses ids that are not ids", async () => {
    await expect(
      updateFlashcardAction(GOAL, "../x", IDLE, form({ front: "Q", back: "A" })),
    ).rejects.toThrow("NOT_FOUND");
  });
});

describe("deleteFlashcardAction", () => {
  it("deletes the card and returns to the deck with a notice", async () => {
    api.deleteFlashcard.mockResolvedValue(undefined);

    await expect(deleteFlashcardAction(GOAL, CARD)).rejects.toThrow(
      `REDIRECT:${DECK}?notice=card-deleted`,
    );

    expect(api.deleteFlashcard).toHaveBeenCalledWith("access-token-123", CARD);
  });

  it.each([
    [409, "GOAL_ARCHIVED", "goal-archived"],
    [503, "UNAVAILABLE", "card-failed"],
    [0, "API_UNREACHABLE", "card-failed"],
  ])("explains a refusal (%i %s) with the notice %s", async (status, code, notice) => {
    api.deleteFlashcard.mockRejectedValue(new ApiError(status, code, "no"));

    await expect(deleteFlashcardAction(GOAL, CARD)).rejects.toThrow(
      `REDIRECT:${DECK}?notice=${notice}`,
    );
  });

  it("sends someone else's card to the not-found page", async () => {
    api.deleteFlashcard.mockRejectedValue(new ApiError(404, "FLASHCARD_NOT_FOUND", "no"));

    await expect(deleteFlashcardAction(GOAL, CARD)).rejects.toThrow("NOT_FOUND");
  });
});

describe("reviewFlashcardAction", () => {
  it("sends only the rating and the key, then returns to the review for the next card", async () => {
    api.reviewFlashcard.mockResolvedValue({});

    await expect(
      reviewFlashcardAction(
        GOAL,
        CARD,
        form({ rating: "good", key: KEY, interval_days: "999", due_at: "2030-01-01" }),
      ),
    ).rejects.toThrow(`REDIRECT:${REVIEW}`);

    expect(api.reviewFlashcard).toHaveBeenCalledTimes(1);
    expect(api.reviewFlashcard).toHaveBeenCalledWith("access-token-123", CARD, "good", KEY);
  });

  it.each(["again", "hard", "good", "easy"])("passes the rating %s through", async (rating) => {
    api.reviewFlashcard.mockResolvedValue({});

    await expect(reviewFlashcardAction(GOAL, CARD, form({ rating, key: KEY }))).rejects.toThrow(
      "REDIRECT",
    );

    expect(api.reviewFlashcard.mock.calls[0]?.[2]).toBe(rating);
  });

  it.each([
    ["an unknown rating", { rating: "perfect", key: KEY }],
    ["a missing rating", { key: KEY }],
    ["a missing key", { rating: "good" }],
    ["a malformed key", { rating: "good", key: "has spaces!" }],
  ])("refuses %s without calling the API", async (_name, fields) => {
    await expect(reviewFlashcardAction(GOAL, CARD, form(fields))).rejects.toThrow(
      `REDIRECT:${REVIEW}?notice=review-failed`,
    );

    expect(api.reviewFlashcard).not.toHaveBeenCalled();
  });

  it.each([
    [409, "GOAL_ARCHIVED", "goal-archived"],
    [422, "INVALID", "review-failed"],
    [0, "API_UNREACHABLE", "review-failed"],
  ])("explains a refusal (%i %s) with the notice %s", async (status, code, notice) => {
    api.reviewFlashcard.mockRejectedValue(new ApiError(status, code, "no"));

    await expect(
      reviewFlashcardAction(GOAL, CARD, form({ rating: "good", key: KEY })),
    ).rejects.toThrow(`REDIRECT:${REVIEW}?notice=${notice}`);
  });

  it("sends someone else's card to the not-found page and an ended session to sign-in", async () => {
    api.reviewFlashcard.mockRejectedValueOnce(new ApiError(404, "FLASHCARD_NOT_FOUND", "no"));
    await expect(
      reviewFlashcardAction(GOAL, CARD, form({ rating: "good", key: KEY })),
    ).rejects.toThrow("NOT_FOUND");

    api.reviewFlashcard.mockRejectedValueOnce(new ApiError(401, "UNAUTHENTICATED", "no"));
    await expect(
      reviewFlashcardAction(GOAL, CARD, form({ rating: "good", key: KEY })),
    ).rejects.toThrow(/REDIRECT:\/sign-in\?.*ended/);
  });

  it("refuses ids that are not ids", async () => {
    await expect(
      reviewFlashcardAction("x", CARD, form({ rating: "good", key: KEY })),
    ).rejects.toThrow("NOT_FOUND");
  });
});
