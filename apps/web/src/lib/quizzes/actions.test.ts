// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest";

const session = vi.hoisted(() => ({
  getSessionUser: vi.fn(),
  getAccessToken: vi.fn(),
}));
const api = vi.hoisted(() => ({
  startQuiz: vi.fn(),
  cancelJob: vi.fn(),
  retryJob: vi.fn(),
  fetchQuiz: vi.fn(),
  submitQuiz: vi.fn(),
  reviewAnswer: vi.fn(),
  regradeAttempt: vi.fn(),
}));

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
  cancelMarkingAction,
  cancelQuizAction,
  regradeAction,
  retryQuizAction,
  reviewAnswerAction,
  startQuizAction,
  submitQuizAction,
} from "@/lib/quizzes/actions";
import { answerField } from "@/lib/quizzes/answers";
import { GOAL, ITEM, JOB } from "@/test-support/lessons";
import { A3, ATTEMPT, Q1, Q2, Q3, QUIZ, quiz } from "@/test-support/quizzes";

const STUDY = `/goals/${GOAL}/learn/${ITEM}`;
const QUIZ_PAGE = `${STUDY}/quiz/${QUIZ}`;
const RESULTS = `${STUDY}/results/${ATTEMPT}`;

function form(fields: Record<string, string | string[]> = {}): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(fields)) {
    for (const one of Array.isArray(value) ? value : [value]) data.append(key, one);
  }
  return data;
}

beforeEach(() => {
  vi.clearAllMocks();
  session.getSessionUser.mockResolvedValue({
    id: "11111111-1111-4111-8111-111111111111",
    email: "a@b.c",
  });
  session.getAccessToken.mockResolvedValue("access-token-123");
});

describe("startQuizAction", () => {
  it("starts a quiz with the caller's token and returns to the topic to follow it", async () => {
    api.startQuiz.mockResolvedValue({ id: JOB });

    await expect(startQuizAction(GOAL, ITEM, "check")).rejects.toThrow(`REDIRECT:${STUDY}`);

    expect(api.startQuiz).toHaveBeenCalledWith("access-token-123", ITEM, "check");
  });

  it("asks for a practice quiz only when told to, and never for anything else", async () => {
    api.startQuiz.mockResolvedValue({ id: JOB });

    await expect(startQuizAction(GOAL, ITEM, "practice")).rejects.toThrow("REDIRECT");
    await expect(startQuizAction(GOAL, ITEM, "exam" as never)).rejects.toThrow("REDIRECT");

    expect(api.startQuiz.mock.calls.map((call) => call[2])).toEqual(["practice", "check"]);
  });

  it.each([
    ["QUIZ_PENDING", 409, "quiz-pending"],
    ["LESSON_REQUIRED", 409, "lesson-required"],
    ["QUIZ_LIMIT_REACHED", 429, "quiz-limit"],
    ["AI_NOT_CONFIGURED", 503, "ai-unavailable"],
    ["GOAL_ARCHIVED", 409, "goal-archived"],
    ["ROADMAP_NOT_CURRENT", 409, "roadmap-not-current"],
    ["TOPIC_NOT_LESSONABLE", 422, "not-lessonable"],
    ["SOMETHING_ELSE", 409, "status-conflict"],
    ["API_UNREACHABLE", 0, "unavailable"],
  ])("explains a refusal with %s through a notice", async (code, status, notice) => {
    api.startQuiz.mockRejectedValue(new ApiError(status, code, "refused"));

    await expect(startQuizAction(GOAL, ITEM, "check")).rejects.toThrow(
      `REDIRECT:${STUDY}?notice=${notice}`,
    );
  });

  it("stays quiet when the quiz is already being written", async () => {
    api.startQuiz.mockRejectedValue(new ApiError(409, "QUIZ_JOB_ACTIVE", "busy"));

    await expect(startQuizAction(GOAL, ITEM, "check")).rejects.toThrow(`REDIRECT:${STUDY}`);
  });

  it("sends a missing or someone else's topic to the not-found page", async () => {
    api.startQuiz.mockRejectedValue(new ApiError(404, "TOPIC_NOT_FOUND", "no"));

    await expect(startQuizAction(GOAL, ITEM, "check")).rejects.toThrow("NOT_FOUND");
  });

  it("sends an ended session to sign-in with the marker that shows the form", async () => {
    api.startQuiz.mockRejectedValue(new ApiError(401, "UNAUTHENTICATED", "no"));

    await expect(startQuizAction(GOAL, ITEM, "check")).rejects.toThrow(
      /REDIRECT:\/sign-in\?.*ended/,
    );
  });

  it.each(["../me", "123", "", GOAL + "x"])(
    "refuses the identifier %j before it can reach an API path",
    async (bad) => {
      await expect(startQuizAction(bad, ITEM, "check")).rejects.toThrow("NOT_FOUND");
      await expect(startQuizAction(GOAL, bad, "check")).rejects.toThrow("NOT_FOUND");
      expect(api.startQuiz).not.toHaveBeenCalled();
    },
  );

  it("sends a signed-out visitor to sign-in and starts nothing", async () => {
    session.getSessionUser.mockResolvedValue(null);

    await expect(startQuizAction(GOAL, ITEM, "check")).rejects.toThrow(/REDIRECT:\/sign-in/);
    expect(api.startQuiz).not.toHaveBeenCalled();
  });
});

describe("cancelling and retrying", () => {
  it("cancels a quiz job and says so", async () => {
    api.cancelJob.mockResolvedValue({});

    await expect(cancelQuizAction(GOAL, ITEM, JOB)).rejects.toThrow(
      `REDIRECT:${STUDY}?notice=quiz-cancelled`,
    );
    expect(api.cancelJob).toHaveBeenCalledWith("access-token-123", JOB);
  });

  it("cancels a marking job and returns to the results", async () => {
    api.cancelJob.mockResolvedValue({});

    await expect(cancelMarkingAction(GOAL, ITEM, ATTEMPT, JOB)).rejects.toThrow(
      `REDIRECT:${RESULTS}?notice=marking-cancelled`,
    );
  });

  it("retries a failed quiz job and returns to the topic", async () => {
    api.retryJob.mockResolvedValue({ id: JOB });

    await expect(retryQuizAction(GOAL, ITEM, JOB)).rejects.toThrow(`REDIRECT:${STUDY}`);
    expect(api.retryJob).toHaveBeenCalledWith("access-token-123", JOB);
  });

  it("explains why a retry was refused", async () => {
    api.retryJob.mockRejectedValue(new ApiError(409, "QUIZ_PENDING", "no"));

    await expect(retryQuizAction(GOAL, ITEM, JOB)).rejects.toThrow(
      `REDIRECT:${STUDY}?notice=quiz-pending`,
    );
  });

  it("checks every identifier", async () => {
    await expect(cancelQuizAction(GOAL, ITEM, "nope")).rejects.toThrow("NOT_FOUND");
    await expect(retryQuizAction(GOAL, "nope", JOB)).rejects.toThrow("NOT_FOUND");
    await expect(cancelMarkingAction(GOAL, ITEM, "nope", JOB)).rejects.toThrow("NOT_FOUND");
    expect(api.cancelJob).not.toHaveBeenCalled();
    expect(api.retryJob).not.toHaveBeenCalled();
  });
});

describe("submitQuizAction", () => {
  const answers = {
    [answerField(Q1)]: "b",
    [answerField(Q2)]: "true",
    [answerField(Q3)]: "  in my words ",
  };

  it("sends the answers read against the quiz's own questions and goes to the results", async () => {
    api.fetchQuiz.mockResolvedValue(quiz());
    api.submitQuiz.mockResolvedValue({ id: ATTEMPT });

    await expect(submitQuizAction(GOAL, ITEM, QUIZ, form(answers))).rejects.toThrow(
      `REDIRECT:${RESULTS}`,
    );

    expect(api.submitQuiz).toHaveBeenCalledWith("access-token-123", QUIZ, {
      answers: [
        { question_id: Q1, option_id: "b" },
        { question_id: Q2, option_id: "true" },
        { question_id: Q3, text: "in my words" },
      ],
    });
  });

  it("sends only answers and no owner, score or status", async () => {
    api.fetchQuiz.mockResolvedValue(quiz());
    api.submitQuiz.mockResolvedValue({ id: ATTEMPT });

    await expect(
      submitQuizAction(
        GOAL,
        ITEM,
        QUIZ,
        form({ ...answers, user_id: "someone", percent: "100", status: "graded", is_correct: "1" }),
      ),
    ).rejects.toThrow("REDIRECT");

    const body = api.submitQuiz.mock.calls[0]?.[2] as Record<string, unknown>;
    expect(Object.keys(body)).toEqual(["answers"]);
    expect(JSON.stringify(body)).not.toMatch(/someone|percent|graded|is_correct/);
  });

  it("submits a blank form as all questions skipped", async () => {
    api.fetchQuiz.mockResolvedValue(quiz());
    api.submitQuiz.mockResolvedValue({ id: ATTEMPT });

    await expect(submitQuizAction(GOAL, ITEM, QUIZ, form())).rejects.toThrow("REDIRECT");

    expect(api.submitQuiz.mock.calls[0]?.[2]).toEqual({ answers: [] });
  });

  it("shows the earlier results instead of submitting a quiz that was already submitted", async () => {
    api.fetchQuiz.mockResolvedValue(
      quiz({
        status: "submitted",
        attempt: {
          id: ATTEMPT,
          status: "graded",
          submitted_at: "2026-10-11T10:05:00Z",
          percent: 80,
        },
      }),
    );

    await expect(submitQuizAction(GOAL, ITEM, QUIZ, form(answers))).rejects.toThrow(
      `REDIRECT:${RESULTS}`,
    );
    expect(api.submitQuiz).not.toHaveBeenCalled();
  });

  it("follows a double submit to the results of the first one", async () => {
    api.fetchQuiz.mockResolvedValueOnce(quiz()).mockResolvedValueOnce(
      quiz({
        status: "submitted",
        attempt: {
          id: ATTEMPT,
          status: "grading",
          submitted_at: "2026-10-11T10:05:00Z",
          percent: null,
        },
      }),
    );
    api.submitQuiz.mockRejectedValue(new ApiError(409, "QUIZ_ALREADY_SUBMITTED", "twice"));

    await expect(submitQuizAction(GOAL, ITEM, QUIZ, form(answers))).rejects.toThrow(
      `REDIRECT:${RESULTS}`,
    );
  });

  it.each([
    [new ApiError(409, "GOAL_ARCHIVED", "x"), "goal-archived"],
    [new ApiError(422, "UNKNOWN_OPTION", "x"), "answers-invalid"],
    [new ApiError(0, "API_UNREACHABLE", "x"), "unavailable"],
  ])("explains a refused submission through a notice (%#)", async (error, notice) => {
    api.fetchQuiz.mockResolvedValue(quiz());
    api.submitQuiz.mockRejectedValue(error);

    await expect(submitQuizAction(GOAL, ITEM, QUIZ, form(answers))).rejects.toThrow(
      `REDIRECT:${QUIZ_PAGE}?notice=${notice}`,
    );
  });

  it("treats a missing or someone else's quiz as not found", async () => {
    api.fetchQuiz.mockRejectedValue(new ApiError(404, "QUIZ_NOT_FOUND", "no"));

    await expect(submitQuizAction(GOAL, ITEM, QUIZ, form(answers))).rejects.toThrow("NOT_FOUND");
    expect(api.submitQuiz).not.toHaveBeenCalled();
  });

  it("refuses a quiz that does not belong to the goal and topic in the URL", async () => {
    api.fetchQuiz.mockResolvedValue(quiz({ goal_id: "99999999-9999-4999-8999-000000000000" }));
    await expect(submitQuizAction(GOAL, ITEM, QUIZ, form(answers))).rejects.toThrow("NOT_FOUND");

    api.fetchQuiz.mockResolvedValue(quiz({ item_id: "99999999-9999-4999-8999-000000000000" }));
    await expect(submitQuizAction(GOAL, ITEM, QUIZ, form(answers))).rejects.toThrow("NOT_FOUND");
    expect(api.submitQuiz).not.toHaveBeenCalled();
  });

  it("checks every identifier before calling the API", async () => {
    await expect(submitQuizAction(GOAL, ITEM, "../x", form())).rejects.toThrow("NOT_FOUND");
    expect(api.fetchQuiz).not.toHaveBeenCalled();
  });
});

describe("reviewAnswerAction", () => {
  it("sends the ticked rubric points and goes back to the results with a notice", async () => {
    api.reviewAnswer.mockResolvedValue({ id: ATTEMPT });

    await expect(
      reviewAnswerAction(GOAL, ITEM, ATTEMPT, A3, form({ met: ["p1", "p2"] })),
    ).rejects.toThrow(`REDIRECT:${RESULTS}?notice=reviewed`);

    expect(api.reviewAnswer).toHaveBeenCalledWith("access-token-123", A3, ["p1", "p2"]);
  });

  it("sends nothing but well-formed point ids, once each, and never a score", async () => {
    api.reviewAnswer.mockResolvedValue({ id: ATTEMPT });

    await expect(
      reviewAnswerAction(
        GOAL,
        ITEM,
        ATTEMPT,
        A3,
        form({ met: ["p1", "p1", "points", "p999", "../x", "p2"], points: "3" }),
      ),
    ).rejects.toThrow("REDIRECT");

    expect(api.reviewAnswer).toHaveBeenCalledWith("access-token-123", A3, ["p1", "p2"]);
  });

  it("accepts a review that ticks nothing: the answer covered no point", async () => {
    api.reviewAnswer.mockResolvedValue({ id: ATTEMPT });

    await expect(reviewAnswerAction(GOAL, ITEM, ATTEMPT, A3, form())).rejects.toThrow("REDIRECT");

    expect(api.reviewAnswer).toHaveBeenCalledWith("access-token-123", A3, []);
  });

  it.each([
    [new ApiError(409, "GOAL_ARCHIVED", "x"), "goal-archived"],
    [new ApiError(409, "NOT_REVIEWABLE", "x"), "not-reviewable"],
    [new ApiError(0, "API_UNREACHABLE", "x"), "unavailable"],
  ])("explains a refused review through a notice (%#)", async (error, notice) => {
    api.reviewAnswer.mockRejectedValue(error);

    await expect(reviewAnswerAction(GOAL, ITEM, ATTEMPT, A3, form())).rejects.toThrow(
      `REDIRECT:${RESULTS}?notice=${notice}`,
    );
  });

  it("treats someone else's answer as not found", async () => {
    api.reviewAnswer.mockRejectedValue(new ApiError(404, "ANSWER_NOT_FOUND", "no"));

    await expect(reviewAnswerAction(GOAL, ITEM, ATTEMPT, A3, form())).rejects.toThrow("NOT_FOUND");
  });
});

describe("regradeAction", () => {
  it("asks for the short answers to be marked again and returns to the results", async () => {
    api.regradeAttempt.mockResolvedValue({ id: JOB });

    await expect(regradeAction(GOAL, ITEM, ATTEMPT)).rejects.toThrow(`REDIRECT:${RESULTS}`);
    expect(api.regradeAttempt).toHaveBeenCalledWith("access-token-123", ATTEMPT);
  });

  it.each([
    ["GRADING_RETRIES_EXHAUSTED", 409, `${RESULTS}?notice=marking-exhausted`],
    ["GRADING_ACTIVE", 409, RESULTS],
    ["GOAL_ARCHIVED", 409, `${RESULTS}?notice=goal-archived`],
    ["NOT_GRADING", 409, `${RESULTS}?notice=status-conflict`],
    ["API_UNREACHABLE", 0, `${RESULTS}?notice=unavailable`],
  ])("handles the refusal %s", async (code, status, target) => {
    api.regradeAttempt.mockRejectedValue(new ApiError(status, code, "no"));

    await expect(regradeAction(GOAL, ITEM, ATTEMPT)).rejects.toThrow(`REDIRECT:${target}`);
  });
});
