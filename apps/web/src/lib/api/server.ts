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
export type Me = components["schemas"]["Me"];
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

function toApiError(response: Response, body: unknown): ApiError {
  const problem = (typeof body === "object" && body !== null ? body : {}) as Partial<ProblemDetail>;
  const fieldErrors: Record<string, string> = {};
  for (const error of problem.errors ?? []) {
    // "body.title" -> "title"; keep the first message per field.
    const field = error.field.replace(/^(body|query|path)\./, "");
    fieldErrors[field] ??= error.message;
  }
  return new ApiError(
    response.status,
    problem.code ?? `HTTP_${response.status}`,
    problem.detail ?? "Request failed.",
    {
      requestId: problem.request_id ?? response.headers.get("x-request-id") ?? undefined,
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

export function fetchMe(accessToken: string): Promise<Me> {
  return call(() => client(accessToken).GET("/v1/me"));
}

export function fetchGoals(
  accessToken: string,
  query: { cursor?: string; limit?: number } = {},
): Promise<GoalPage> {
  return call(() => client(accessToken).GET("/v1/goals", { params: { query } }));
}

export function createGoal(accessToken: string, body: GoalCreate): Promise<Goal> {
  return call(() => client(accessToken).POST("/v1/goals", { body }));
}
