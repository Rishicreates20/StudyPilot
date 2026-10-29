/**
 * Typed client for the StudyPilot API, used from the server only (Server Components and Server
 * Actions). The access token stays on the server and is sent as `Authorization: Bearer`; the API
 * verifies it on every call and derives the caller's identity from it, so nothing sent from here
 * (or from a browser) can claim to be another user.
 *
 * Request and response types come from the API's OpenAPI document via @studypilot/contracts.
 */
import type { components, paths } from "@studypilot/contracts";
import createClient from "openapi-fetch";

import { getServerEnv } from "@/lib/env";

export type Goal = components["schemas"]["Goal"];
export type GoalPage = components["schemas"]["GoalPage"];
export type GoalCreate = components["schemas"]["GoalCreate"];
export type GoalUpdate = components["schemas"]["GoalUpdate"];
export type GoalSummary = components["schemas"]["GoalSummary"];
export type GoalStatus = Goal["status"];
export type Me = components["schemas"]["Me"];
export type MeUpdate = components["schemas"]["MeUpdate"];
export type Preferences = components["schemas"]["Preferences"];
export type GenerationJob = components["schemas"]["GenerationJob"];
export type JobList = components["schemas"]["JobList"];
export type Roadmap = components["schemas"]["Roadmap"];
export type RoadmapSummary = components["schemas"]["RoadmapSummary"];
export type RoadmapList = components["schemas"]["RoadmapList"];
export type RoadmapItem = components["schemas"]["RoadmapItem"];
export type RoadmapModule = components["schemas"]["RoadmapModule"];
export type JobStatus = GenerationJob["status"];
export type StudyView = components["schemas"]["StudyView"];
export type LessonDetail = components["schemas"]["LessonDetail"];
export type LessonVersion = components["schemas"]["LessonVersion"];
export type LessonDocument = components["schemas"]["Lesson"];
export type LessonSection = components["schemas"]["LessonSection"];
export type LessonBlock = LessonSection["blocks"][number];
export type LessonRequest = components["schemas"]["LessonRequest"];
export type LessonAdjust = NonNullable<LessonRequest["adjust"]>;
export type ProgressState = components["schemas"]["ProgressState"];
export type ProgressUpdate = components["schemas"]["ProgressUpdate"];
export type ItemStudy = components["schemas"]["ItemStudy"];
export type NeighbourTopic = components["schemas"]["NeighbourTopic"];
export type TopicInfo = components["schemas"]["TopicInfo"];
export type OutlineEntry = components["schemas"]["OutlineEntry"];
type ProblemDetail = components["schemas"]["ProblemDetail"];

const REQUEST_TIMEOUT_MS = 10_000;

/** A failed API call, reduced to what the UI may safely show. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string | undefined;
  /** Field-level messages from a 422, keyed by the request body field ("title"). */
  readonly fieldErrors: Readonly<Record<string, string>>;

  constructor(
    status: number,
    code: string,
    message: string,
    options: { requestId?: string; fieldErrors?: Record<string, string> } = {},
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.requestId = options.requestId;
    this.fieldErrors = options.fieldErrors ?? {};
  }

  get isUnauthenticated(): boolean {
    return this.status === 401;
  }
}

const textOf = (value: unknown): string | undefined =>
  typeof value === "string" ? value : undefined;

/**
 * An ApiError from whatever came back. The body is NOT trusted to be a problem document: a proxy,
 * a gateway or a misbehaving server can answer with any JSON, so only well-typed values are used
 * and everything else falls back to generic wording (never a crash, never an object as text).
 */
function toApiError(response: Response, body: unknown): ApiError {
  const problem: Partial<Record<keyof ProblemDetail, unknown>> =
    typeof body === "object" && body !== null && !Array.isArray(body) ? body : {};
  const fieldErrors: Record<string, string> = {};
  for (const error of Array.isArray(problem.errors) ? (problem.errors as unknown[]) : []) {
    if (typeof error !== "object" || error === null) continue;
    const { field, message } = error as Record<string, unknown>;
    if (typeof field !== "string" || typeof message !== "string") continue;
    // "body.title" -> "title", "body.languages.0" -> "languages": a form shows an error on the
    // list item against its field. Keep the first message per field.
    const name = field.replace(/^(body|query|path)\./, "").split(".")[0] ?? "";
    fieldErrors[name] ??= message;
  }
  return new ApiError(
    response.status,
    textOf(problem.code) ?? `HTTP_${response.status}`,
    textOf(problem.detail) ?? "Request failed.",
    {
      requestId: textOf(problem.request_id) ?? response.headers.get("x-request-id") ?? undefined,
      fieldErrors,
    },
  );
}

function client(accessToken: string) {
  return createClient<paths>({
    baseUrl: getServerEnv().API_INTERNAL_BASE_URL,
    headers: { Authorization: `Bearer ${accessToken}` },
    fetch: (request) =>
      fetch(request, { cache: "no-store", signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS) }),
  });
}

/** Run a call, turning transport failures (down, timeout) into an ApiError the UI can handle. */
async function call<T>(
  run: () => Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  let result: Awaited<ReturnType<typeof run>>;
  try {
    result = await run();
  } catch {
    throw new ApiError(0, "API_UNREACHABLE", "The service is unreachable right now.");
  }
  if (result.data !== undefined) return result.data;
  throw toApiError(result.response, result.error);
}

/** Like `call`, for endpoints that answer 204 No Content. */
async function callWithoutBody(
  run: () => Promise<{ error?: unknown; response: Response }>,
): Promise<void> {
  let result: Awaited<ReturnType<typeof run>>;
  try {
    result = await run();
  } catch {
    throw new ApiError(0, "API_UNREACHABLE", "The service is unreachable right now.");
  }
  if (!result.response.ok) throw toApiError(result.response, result.error);
}

export function fetchMe(accessToken: string): Promise<Me> {
  return call(() => client(accessToken).GET("/v1/me"));
}

export function updateMe(accessToken: string, body: MeUpdate): Promise<Me> {
  return call(() => client(accessToken).PATCH("/v1/me", { body }));
}

export function completeOnboarding(accessToken: string): Promise<Me> {
  return call(() => client(accessToken).POST("/v1/me/onboarding/complete"));
}

export function fetchGoals(
  accessToken: string,
  query: { status?: GoalStatus[]; cursor?: string; limit?: number } = {},
): Promise<GoalPage> {
  return call(() => client(accessToken).GET("/v1/goals", { params: { query } }));
}

export function fetchGoalSummary(accessToken: string): Promise<GoalSummary> {
  return call(() => client(accessToken).GET("/v1/goals/summary"));
}

export function fetchGoal(accessToken: string, goalId: string): Promise<Goal> {
  return call(() =>
    client(accessToken).GET("/v1/goals/{goal_id}", { params: { path: { goal_id: goalId } } }),
  );
}

export function createGoal(accessToken: string, body: GoalCreate): Promise<Goal> {
  return call(() => client(accessToken).POST("/v1/goals", { body }));
}

export function updateGoal(accessToken: string, goalId: string, body: GoalUpdate): Promise<Goal> {
  return call(() =>
    client(accessToken).PATCH("/v1/goals/{goal_id}", {
      params: { path: { goal_id: goalId } },
      body,
    }),
  );
}

export function setGoalStatus(
  accessToken: string,
  goalId: string,
  status: GoalStatus,
): Promise<Goal> {
  return call(() =>
    client(accessToken).PUT("/v1/goals/{goal_id}/status", {
      params: { path: { goal_id: goalId } },
      body: { status },
    }),
  );
}

export function deleteGoal(accessToken: string, goalId: string): Promise<void> {
  return callWithoutBody(() =>
    client(accessToken).DELETE("/v1/goals/{goal_id}", { params: { path: { goal_id: goalId } } }),
  );
}

/** Queue a roadmap generation. The answer is the job (202); the plan arrives later. */
export function startRoadmap(
  accessToken: string,
  goalId: string,
  body: { feedback?: string | null } = {},
): Promise<GenerationJob> {
  return call(() =>
    client(accessToken).POST("/v1/goals/{goal_id}/roadmaps", {
      params: { path: { goal_id: goalId } },
      body,
    }),
  );
}

export function fetchRoadmaps(accessToken: string, goalId: string): Promise<RoadmapList> {
  return call(() =>
    client(accessToken).GET("/v1/goals/{goal_id}/roadmaps", {
      params: { path: { goal_id: goalId } },
    }),
  );
}

export function fetchGoalJobs(accessToken: string, goalId: string, limit = 5): Promise<JobList> {
  return call(() =>
    client(accessToken).GET("/v1/goals/{goal_id}/jobs", {
      params: { path: { goal_id: goalId }, query: { limit } },
    }),
  );
}

export function fetchRoadmap(accessToken: string, roadmapId: string): Promise<Roadmap> {
  return call(() =>
    client(accessToken).GET("/v1/roadmaps/{roadmap_id}", {
      params: { path: { roadmap_id: roadmapId } },
    }),
  );
}

export function makeRoadmapCurrent(
  accessToken: string,
  roadmapId: string,
): Promise<RoadmapSummary> {
  return call(() =>
    client(accessToken).POST("/v1/roadmaps/{roadmap_id}/make-current", {
      params: { path: { roadmap_id: roadmapId } },
    }),
  );
}

export function cancelJob(accessToken: string, jobId: string): Promise<GenerationJob> {
  return call(() =>
    client(accessToken).POST("/v1/jobs/{job_id}/cancel", { params: { path: { job_id: jobId } } }),
  );
}

export function retryJob(accessToken: string, jobId: string): Promise<GenerationJob> {
  return call(() =>
    client(accessToken).POST("/v1/jobs/{job_id}/retry", { params: { path: { job_id: jobId } } }),
  );
}

/** Queue a lesson for a roadmap topic, or a new version of it. The answer is the job (202). */
export function startLesson(
  accessToken: string,
  itemId: string,
  body: LessonRequest,
): Promise<GenerationJob> {
  return call(() =>
    client(accessToken).POST("/v1/roadmap-items/{item_id}/lessons", {
      params: { path: { item_id: itemId } },
      body,
    }),
  );
}

/** Everything the study page shows for one topic; `lessonId` asks for an earlier version. */
export function fetchStudy(
  accessToken: string,
  itemId: string,
  lessonId?: string,
): Promise<StudyView> {
  return call(() =>
    client(accessToken).GET("/v1/roadmap-items/{item_id}/study", {
      params: { path: { item_id: itemId }, query: lessonId ? { lesson_id: lessonId } : {} },
    }),
  );
}

/** Replace the learner's saved place in a lesson. */
export function saveLessonProgress(
  accessToken: string,
  lessonId: string,
  body: ProgressUpdate,
): Promise<ProgressState> {
  return call(() =>
    client(accessToken).PUT("/v1/lessons/{lesson_id}/progress", {
      params: { path: { lesson_id: lessonId } },
      body,
    }),
  );
}

export type QuizDetail = components["schemas"]["QuizDetail"];
export type QuizSummary = components["schemas"]["QuizSummary"];
export type QuestionOut = components["schemas"]["QuestionOut"];
export type AttemptResult = components["schemas"]["AttemptResult"];
export type AnswerResult = components["schemas"]["AnswerResult"];
export type AttemptBrief = components["schemas"]["AttemptBrief"];
export type AttemptSubmit = components["schemas"]["AttemptSubmit"];
export type TopicAssessment = components["schemas"]["TopicAssessment"];
export type TopicMastery = components["schemas"]["TopicMasteryOut"];
export type GoalProgress = components["schemas"]["GoalProgress"];
export type TopicProgress = components["schemas"]["TopicProgress"];
export type Recommendation = components["schemas"]["RecommendationOut"];
export type QuizPurpose = NonNullable<components["schemas"]["QuizRequest"]["purpose"]>;
export type MasteryBand = TopicMastery["band"];

/** Queue a quiz for a roadmap topic, written from its lesson. The answer is the job (202). */
export function startQuiz(
  accessToken: string,
  itemId: string,
  purpose: QuizPurpose,
): Promise<GenerationJob> {
  return call(() =>
    client(accessToken).POST("/v1/roadmap-items/{item_id}/quizzes", {
      params: { path: { item_id: itemId } },
      body: { purpose },
    }),
  );
}

/** Where a topic stands on quizzes and mastery, and whether a new quiz can be started. */
export function fetchAssessment(accessToken: string, itemId: string): Promise<TopicAssessment> {
  return call(() =>
    client(accessToken).GET("/v1/roadmap-items/{item_id}/assessment", {
      params: { path: { item_id: itemId } },
    }),
  );
}

/** A quiz to take: questions and options only, never a correct answer. */
export function fetchQuiz(accessToken: string, quizId: string): Promise<QuizDetail> {
  return call(() =>
    client(accessToken).GET("/v1/quizzes/{quiz_id}", { params: { path: { quiz_id: quizId } } }),
  );
}

/** Submit the answers of a quiz. Correctness comes back in the result, not before. */
export function submitQuiz(
  accessToken: string,
  quizId: string,
  body: AttemptSubmit,
  idempotencyKey?: string,
): Promise<AttemptResult> {
  return call(() =>
    client(accessToken).POST("/v1/quizzes/{quiz_id}/attempts", {
      params: {
        path: { quiz_id: quizId },
        header: idempotencyKey ? { "Idempotency-Key": idempotencyKey } : {},
      },
      body,
    }),
  );
}

export function fetchAttempt(accessToken: string, attemptId: string): Promise<AttemptResult> {
  return call(() =>
    client(accessToken).GET("/v1/quiz-attempts/{attempt_id}", {
      params: { path: { attempt_id: attemptId } },
    }),
  );
}

/** Ask for the short answers of an attempt to be marked again after marking failed. */
export function regradeAttempt(accessToken: string, attemptId: string): Promise<GenerationJob> {
  return call(() =>
    client(accessToken).POST("/v1/quiz-attempts/{attempt_id}/regrade", {
      params: { path: { attempt_id: attemptId } },
    }),
  );
}

/** Say which rubric points the learner's own short answer covered. */
export function reviewAnswer(
  accessToken: string,
  answerId: string,
  metPointIds: string[],
): Promise<AttemptResult> {
  return call(() =>
    client(accessToken).PUT("/v1/quiz-answers/{answer_id}/review", {
      params: { path: { answer_id: answerId } },
      body: { met_point_ids: metPointIds },
    }),
  );
}

/** Mastery of every topic of a goal's current roadmap, and the recommended next step. */
export function fetchGoalProgress(accessToken: string, goalId: string): Promise<GoalProgress> {
  return call(() =>
    client(accessToken).GET("/v1/goals/{goal_id}/progress", {
      params: { path: { goal_id: goalId } },
    }),
  );
}

export type StudyDocument = components["schemas"]["Document"];
export type Export = components["schemas"]["Export"];
export type ExportList = components["schemas"]["ExportList"];
export type ExportFormat = Export["format"];
export type ExportStatus = Export["status"];
export type LessonExportFormat = components["schemas"]["LessonExportRequest"]["format"];
export type RoadmapExportFormat = components["schemas"]["RoadmapExportRequest"]["format"];
export type DownloadLink = components["schemas"]["DownloadLink"];
export type DocumentList = components["schemas"]["DocumentList"];
export type DocumentPages = components["schemas"]["DocumentPages"];
export type DocumentPage = components["schemas"]["DocumentPage"];
export type DocumentWarning = components["schemas"]["DocumentWarning"];
export type SearchResult = components["schemas"]["SearchResult"];
export type PassageHit = components["schemas"]["PassageHit"];
export type Citation = components["schemas"]["Citation"];
export type DocumentStatus = StudyDocument["status"];
export type DocumentKind = StudyDocument["kind"];

/** A file upload may take a while on a slow link; everything else is a quick call. */
const UPLOAD_TIMEOUT_MS = 60_000;

export function fetchDocuments(accessToken: string, goalId: string): Promise<DocumentList> {
  return call(() =>
    client(accessToken).GET("/v1/goals/{goal_id}/documents", {
      params: { path: { goal_id: goalId } },
    }),
  );
}

export function fetchDocument(accessToken: string, documentId: string): Promise<StudyDocument> {
  return call(() =>
    client(accessToken).GET("/v1/documents/{document_id}", {
      params: { path: { document_id: documentId } },
    }),
  );
}

export function fetchDocumentPages(
  accessToken: string,
  documentId: string,
  offset = 0,
  limit = 20,
): Promise<DocumentPages> {
  return call(() =>
    client(accessToken).GET("/v1/documents/{document_id}/pages", {
      params: { path: { document_id: documentId }, query: { offset, limit } },
    }),
  );
}

/**
 * Upload a file. The bytes go to the API as the raw request body: what the file is gets decided
 * there from its content, never from the name or type the browser claims.
 */
export async function uploadDocument(
  accessToken: string,
  goalId: string,
  file: File,
  title: string | null,
): Promise<StudyDocument> {
  const url = new URL(`/v1/goals/${goalId}/documents`, getServerEnv().API_INTERNAL_BASE_URL);
  url.searchParams.set("name", file.name.slice(0, 300) || "upload");
  if (title) url.searchParams.set("title", title);
  let response: Response;
  try {
    response = await fetch(url, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${accessToken}`,
        "Content-Type": "application/octet-stream",
      },
      body: file,
      cache: "no-store",
      signal: AbortSignal.timeout(UPLOAD_TIMEOUT_MS),
    });
  } catch {
    throw new ApiError(0, "API_UNREACHABLE", "The service is unreachable right now.");
  }
  const body: unknown = await response.json().catch(() => undefined);
  if (!response.ok) throw toApiError(response, body);
  return body as StudyDocument;
}

export function pasteDocument(
  accessToken: string,
  goalId: string,
  body: { title: string; text: string },
): Promise<StudyDocument> {
  return call(() =>
    client(accessToken).POST("/v1/goals/{goal_id}/documents/paste", {
      params: { path: { goal_id: goalId } },
      body,
    }),
  );
}

export function renameDocument(
  accessToken: string,
  documentId: string,
  title: string,
): Promise<StudyDocument> {
  return call(() =>
    client(accessToken).PATCH("/v1/documents/{document_id}", {
      params: { path: { document_id: documentId } },
      body: { title },
    }),
  );
}

export function editDocumentPage(
  accessToken: string,
  documentId: string,
  pageNumber: number,
  text: string,
): Promise<DocumentPage> {
  return call(() =>
    client(accessToken).PUT("/v1/documents/{document_id}/pages/{page_number}", {
      params: { path: { document_id: documentId, page_number: pageNumber } },
      body: { text },
    }),
  );
}

export function confirmDocument(accessToken: string, documentId: string): Promise<StudyDocument> {
  return call(() =>
    client(accessToken).POST("/v1/documents/{document_id}/confirm", {
      params: { path: { document_id: documentId } },
    }),
  );
}

export function reprocessDocument(accessToken: string, documentId: string): Promise<StudyDocument> {
  return call(() =>
    client(accessToken).POST("/v1/documents/{document_id}/reprocess", {
      params: { path: { document_id: documentId } },
    }),
  );
}

export function deleteDocument(accessToken: string, documentId: string): Promise<void> {
  return callWithoutBody(() =>
    client(accessToken).DELETE("/v1/documents/{document_id}", {
      params: { path: { document_id: documentId } },
    }),
  );
}

export function searchDocuments(
  accessToken: string,
  goalId: string,
  body: { query: string; document_ids?: string[] | null; limit?: number | null },
): Promise<SearchResult> {
  return call(() =>
    client(accessToken).POST("/v1/goals/{goal_id}/documents/search", {
      params: { path: { goal_id: goalId } },
      body,
    }),
  );
}

/** The original file, as the API streams it (always an attachment). */
export async function downloadDocument(accessToken: string, documentId: string): Promise<Response> {
  const url = new URL(`/v1/documents/${documentId}/file`, getServerEnv().API_INTERNAL_BASE_URL);
  let response: Response;
  try {
    response = await fetch(url, {
      headers: { Authorization: `Bearer ${accessToken}` },
      cache: "no-store",
      signal: AbortSignal.timeout(UPLOAD_TIMEOUT_MS),
    });
  } catch {
    throw new ApiError(0, "API_UNREACHABLE", "The service is unreachable right now.");
  }
  if (!response.ok) throw toApiError(response, await response.json().catch(() => undefined));
  return response;
}

// --- Flashcards -------------------------------------------------------------------------------------

export type Flashcard = components["schemas"]["Flashcard"];
export type FlashcardList = components["schemas"]["FlashcardList"];
export type FlashcardDueQueue = components["schemas"]["FlashcardDueQueue"];
export type FlashcardSummary = components["schemas"]["FlashcardSummary"];
export type FlashcardReviewResult = components["schemas"]["FlashcardReviewResult"];
export type FlashcardRating = components["schemas"]["FlashcardReviewRequest"]["rating"];
export type FlashcardInput = components["schemas"]["FlashcardCreate"];
export type FlashcardEdit = components["schemas"]["FlashcardUpdate"];

export function fetchFlashcards(accessToken: string, goalId: string): Promise<FlashcardList> {
  return call(() =>
    client(accessToken).GET("/v1/goals/{goal_id}/flashcards", {
      params: { path: { goal_id: goalId } },
    }),
  );
}

export function fetchDueFlashcards(
  accessToken: string,
  goalId: string,
  limit = 20,
): Promise<FlashcardDueQueue> {
  return call(() =>
    client(accessToken).GET("/v1/goals/{goal_id}/flashcards/due", {
      params: { path: { goal_id: goalId }, query: { limit } },
    }),
  );
}

export function createFlashcard(
  accessToken: string,
  goalId: string,
  body: FlashcardInput,
): Promise<Flashcard> {
  return call(() =>
    client(accessToken).POST("/v1/goals/{goal_id}/flashcards", {
      params: { path: { goal_id: goalId } },
      body,
    }),
  );
}

export function updateFlashcard(
  accessToken: string,
  cardId: string,
  body: FlashcardEdit,
): Promise<Flashcard> {
  return call(() =>
    client(accessToken).PATCH("/v1/flashcards/{card_id}", {
      params: { path: { card_id: cardId } },
      body,
    }),
  );
}

export function deleteFlashcard(accessToken: string, cardId: string): Promise<void> {
  return callWithoutBody(() =>
    client(accessToken).DELETE("/v1/flashcards/{card_id}", {
      params: { path: { card_id: cardId } },
    }),
  );
}

export function reviewFlashcard(
  accessToken: string,
  cardId: string,
  rating: FlashcardRating,
  idempotencyKey: string,
): Promise<FlashcardReviewResult> {
  return call(() =>
    client(accessToken).POST("/v1/flashcards/{card_id}/reviews", {
      params: { path: { card_id: cardId }, header: { "Idempotency-Key": idempotencyKey } },
      body: { rating },
    }),
  );
}

// --- Exports (PDF notes, revision sheets, roadmaps, slides) ------------------------------------

export function requestLessonExport(
  accessToken: string,
  lessonId: string,
  format: LessonExportFormat,
): Promise<Export> {
  return call(() =>
    client(accessToken).POST("/v1/lessons/{lesson_id}/exports", {
      params: { path: { lesson_id: lessonId } },
      body: { format },
    }),
  );
}

export function requestRoadmapExport(
  accessToken: string,
  roadmapId: string,
  format: RoadmapExportFormat,
): Promise<Export> {
  return call(() =>
    client(accessToken).POST("/v1/roadmaps/{roadmap_id}/exports", {
      params: { path: { roadmap_id: roadmapId } },
      body: { format },
    }),
  );
}

export function fetchExports(accessToken: string, goalId: string): Promise<ExportList> {
  return call(() =>
    client(accessToken).GET("/v1/goals/{goal_id}/exports", {
      params: { path: { goal_id: goalId } },
    }),
  );
}

/** A short-lived signed link to a ready export (null `url` when the API serves files itself). */
export function createDownloadLink(accessToken: string, exportId: string): Promise<DownloadLink> {
  return call(() =>
    client(accessToken).POST("/v1/exports/{export_id}/download-link", {
      params: { path: { export_id: exportId } },
    }),
  );
}

export function deleteExport(accessToken: string, exportId: string): Promise<void> {
  return callWithoutBody(() =>
    client(accessToken).DELETE("/v1/exports/{export_id}", {
      params: { path: { export_id: exportId } },
    }),
  );
}

/** The bytes of a ready export, through the API (used when there is no signed link). */
export async function downloadExportFile(accessToken: string, exportId: string): Promise<Response> {
  const url = new URL(`/v1/exports/${exportId}/file`, getServerEnv().API_INTERNAL_BASE_URL);
  let response: Response;
  try {
    response = await fetch(url, {
      headers: { Authorization: `Bearer ${accessToken}` },
      cache: "no-store",
      signal: AbortSignal.timeout(UPLOAD_TIMEOUT_MS),
    });
  } catch {
    throw new ApiError(0, "API_UNREACHABLE", "The service is unreachable right now.");
  }
  if (!response.ok) throw toApiError(response, await response.json().catch(() => undefined));
  return response;
}
