// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  completeOnboarding,
  createGoal,
  deleteGoal,
  downloadDocument,
  fetchGoal,
  fetchGoalSummary,
  fetchGoals,
  fetchMe,
  searchDocuments,
  setGoalStatus,
  updateGoal,
  updateMe,
  uploadDocument,
} from "@/lib/api/server";

function problem(status: number, body: Record<string, unknown>) {
  return new Response(JSON.stringify({ title: "x", status, ...body }), {
    status,
    headers: { "Content-Type": "application/problem+json", "x-request-id": "req-from-header" },
  });
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

function stubFetch(handler: (request: Request) => Response | Promise<Response>) {
  const fetchMock = vi.fn<(input: Request | string, init?: RequestInit) => Promise<Response>>(
    async (input) => {
      const request = input instanceof Request ? input : new Request(input);
      return handler(request);
    },
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const me = {
  id: "11111111-1111-4111-8111-111111111111",
  email: "a@b.c",
  display_name: null,
  locale: "en",
  timezone: "UTC",
  created_at: "2026-10-09T00:00:00Z",
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("the API client", () => {
  it("sends the access token as a bearer credential and nothing identifying the user", async () => {
    const fetchMock = stubFetch(() => json(me));

    await fetchMe("access-token-123");

    const request = fetchMock.mock.calls[0]?.[0] as Request;
    expect(request.headers.get("authorization")).toBe("Bearer access-token-123");
    expect(new URL(request.url).pathname).toBe("/v1/me");
    expect([...request.headers.keys()].filter((k) => k.includes("user"))).toEqual([]);
  });

  it("never lets the HTTP layer cache a response", async () => {
    const fetchMock = stubFetch(() => json({ items: [], next_cursor: null }));

    await fetchGoals("t", { limit: 5 });

    expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({ cache: "no-store" });
  });

  it("passes pagination as query parameters", async () => {
    const fetchMock = stubFetch(() => json({ items: [], next_cursor: null }));

    await fetchGoals("t", { limit: 12, cursor: "abc" });

    const url = new URL((fetchMock.mock.calls[0]?.[0] as Request).url);
    expect(url.pathname).toBe("/v1/goals");
    expect(url.searchParams.get("limit")).toBe("12");
    expect(url.searchParams.get("cursor")).toBe("abc");
  });

  it("posts a goal as JSON", async () => {
    const fetchMock = stubFetch(() => json({ id: "g1" }, 201));

    await createGoal("t", {
      title: "Learn",
      goal_type: "general",
      current_level: "unknown",
      daily_minutes: 60,
      preferred_languages: ["en"],
    });

    const request = fetchMock.mock.calls[0]?.[0] as Request;
    expect(request.method).toBe("POST");
    expect(await request.json()).toMatchObject({ title: "Learn", daily_minutes: 60 });
  });
});

describe("API failures", () => {
  it("turns a 401 into an ApiError the UI can react to", async () => {
    stubFetch(() => problem(401, { code: "TOKEN_EXPIRED", detail: "Your session has expired." }));

    const error = await fetchMe("t").catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 401, code: "TOKEN_EXPIRED", isUnauthenticated: true });
  });

  it("extracts field errors from a 422, dropping the location prefix", async () => {
    stubFetch(() =>
      problem(422, {
        code: "VALIDATION_ERROR",
        errors: [
          { field: "body.title", message: "Too short", code: "string_too_short" },
          { field: "body.title", message: "Ignored second message", code: "x" },
          { field: "body.daily_minutes", message: "Too small", code: "greater_than_equal" },
          { field: "query.limit", message: "Too big", code: "less_than_equal" },
        ],
      }),
    );

    const error = (await fetchMe("t").catch((e: unknown) => e)) as ApiError;

    expect(error.fieldErrors).toEqual({
      title: "Too short",
      daily_minutes: "Too small",
      limit: "Too big",
    });
  });

  it("carries the request ID so a report can be matched to server logs", async () => {
    stubFetch(() => problem(500, { code: "INTERNAL_ERROR", request_id: "req-123" }));

    const error = (await fetchMe("t").catch((e: unknown) => e)) as ApiError;

    expect(error.requestId).toBe("req-123");
  });

  it("falls back to the response header and a generic code for non-problem bodies", async () => {
    stubFetch(
      () =>
        new Response("<html>Bad gateway</html>", {
          status: 502,
          headers: { "x-request-id": "req-gw" },
        }),
    );

    const error = (await fetchMe("t").catch((e: unknown) => e)) as ApiError;

    expect(error).toMatchObject({ status: 502, code: "HTTP_502", requestId: "req-gw" });
    expect(error.message).not.toContain("<html>");
  });

  // A proxy, gateway or misbehaving server can answer with JSON that is not a problem document.
  // The client must still produce a well-formed ApiError instead of crashing the page.
  it.each([
    ["errors is not a list", { errors: "something broke" }],
    ["an error entry has no field", { errors: [{ message: "x" }] }],
    ["an error entry is not an object", { errors: [null, 3, "x"] }],
    ["field and message are not strings", { errors: [{ field: 7, message: { a: 1 } }] }],
    ["code and detail are not strings", { code: 500, detail: { nested: true } }],
    ["the body is a JSON array", [1, 2, 3]],
    ["the body is JSON null", null],
  ])("turns a malformed JSON error body (%s) into a generic ApiError", async (_, body) => {
    stubFetch(() => json(body, 500));

    const error = (await fetchMe("t").catch((e: unknown) => e)) as ApiError;

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 500, code: "HTTP_500", message: "Request failed." });
    expect(error.fieldErrors).toEqual({});
  });

  it("keeps the well-formed field errors of a partly malformed body", async () => {
    stubFetch(() =>
      problem(422, {
        code: "VALIDATION_ERROR",
        detail: "Invalid.",
        errors: [{ field: "body.title", message: "Too long." }, { message: "no field" }, "junk"],
      }),
    );

    const error = (await fetchMe("t").catch((e: unknown) => e)) as ApiError;

    expect(error).toMatchObject({ status: 422, code: "VALIDATION_ERROR", message: "Invalid." });
    expect(error.fieldErrors).toEqual({ title: "Too long." });
  });

  it("reports an unreachable API as status 0", async () => {
    stubFetch(() => {
      throw new TypeError("fetch failed");
    });

    const error = (await fetchMe("t").catch((e: unknown) => e)) as ApiError;

    expect(error).toMatchObject({ status: 0, code: "API_UNREACHABLE" });
  });

  it("reports a timeout the same way", async () => {
    stubFetch(() => {
      throw new DOMException("The operation timed out.", "TimeoutError");
    });

    const error = (await fetchMe("t").catch((e: unknown) => e)) as ApiError;

    expect(error.status).toBe(0);
  });
});

const GOAL_ID = "11111111-1111-4111-8111-111111111111";

describe("goal management calls", () => {
  it("reads one goal by ID", async () => {
    const fetchMock = stubFetch(() => json({ id: GOAL_ID }));

    await fetchGoal("t", GOAL_ID);

    const request = fetchMock.mock.calls[0]?.[0] as Request;
    expect(request.method).toBe("GET");
    expect(new URL(request.url).pathname).toBe(`/v1/goals/${GOAL_ID}`);
    expect(request.headers.get("authorization")).toBe("Bearer t");
  });

  it("asks for several statuses with a repeated query parameter", async () => {
    const fetchMock = stubFetch(() => json({ items: [], next_cursor: null }));

    await fetchGoals("t", { status: ["active", "paused"], limit: 12 });

    const url = new URL((fetchMock.mock.calls[0]?.[0] as Request).url);
    expect(url.searchParams.getAll("status")).toEqual(["active", "paused"]);
    expect(url.searchParams.get("limit")).toBe("12");
  });

  it("reads the summary", async () => {
    const fetchMock = stubFetch(() => json({ active: 1, paused: 0, completed: 0, archived: 0 }));

    await expect(fetchGoalSummary("t")).resolves.toMatchObject({ active: 1 });

    expect(new URL((fetchMock.mock.calls[0]?.[0] as Request).url).pathname).toBe(
      "/v1/goals/summary",
    );
  });

  it("edits with PATCH and sends exactly the body it was given", async () => {
    const fetchMock = stubFetch(() => json({ id: GOAL_ID }));

    await updateGoal("t", GOAL_ID, { title: "New title", description: null });

    const request = fetchMock.mock.calls[0]?.[0] as Request;
    expect(request.method).toBe("PATCH");
    expect(new URL(request.url).pathname).toBe(`/v1/goals/${GOAL_ID}`);
    expect(await request.json()).toEqual({ title: "New title", description: null });
  });

  it("changes the status with PUT to the status sub-resource", async () => {
    const fetchMock = stubFetch(() => json({ id: GOAL_ID, status: "paused" }));

    await setGoalStatus("t", GOAL_ID, "paused");

    const request = fetchMock.mock.calls[0]?.[0] as Request;
    expect(request.method).toBe("PUT");
    expect(new URL(request.url).pathname).toBe(`/v1/goals/${GOAL_ID}/status`);
    expect(await request.json()).toEqual({ status: "paused" });
  });

  it("treats a 204 on delete as success", async () => {
    const fetchMock = stubFetch(() => new Response(null, { status: 204 }));

    await expect(deleteGoal("t", GOAL_ID)).resolves.toBeUndefined();

    expect((fetchMock.mock.calls[0]?.[0] as Request).method).toBe("DELETE");
  });

  it("turns a refused delete into an ApiError", async () => {
    stubFetch(() => problem(409, { code: "GOAL_NOT_ARCHIVED", detail: "Archive it first." }));

    const error = (await deleteGoal("t", GOAL_ID).catch((e: unknown) => e)) as ApiError;

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 409, code: "GOAL_NOT_ARCHIVED" });
  });

  it("reports an unreachable API on delete the same way as on reads", async () => {
    stubFetch(() => {
      throw new TypeError("fetch failed");
    });

    const error = (await deleteGoal("t", GOAL_ID).catch((e: unknown) => e)) as ApiError;

    expect(error).toMatchObject({ status: 0, code: "API_UNREACHABLE" });
  });
});

describe("profile calls", () => {
  it("updates the profile with PATCH", async () => {
    const fetchMock = stubFetch(() => json(me));

    await updateMe("t", { default_daily_minutes: 45, learning_preferences: [] });

    const request = fetchMock.mock.calls[0]?.[0] as Request;
    expect(request.method).toBe("PATCH");
    expect(new URL(request.url).pathname).toBe("/v1/me");
    expect(await request.json()).toEqual({ default_daily_minutes: 45, learning_preferences: [] });
  });

  it("completes onboarding with POST and no body", async () => {
    const fetchMock = stubFetch(() => json(me));

    await completeOnboarding("t");

    const request = fetchMock.mock.calls[0]?.[0] as Request;
    expect(request.method).toBe("POST");
    expect(new URL(request.url).pathname).toBe("/v1/me/onboarding/complete");
  });
});

describe("field errors", () => {
  it("reports an error on a list item against its field", async () => {
    stubFetch(() =>
      problem(422, {
        code: "VALIDATION_ERROR",
        errors: [
          { field: "body.learning_preferences.1", message: "Not one of the choices", code: "x" },
          { field: "body.preferred_languages.0", message: "Choose from: en, hi, or.", code: "x" },
        ],
      }),
    );

    const error = (await updateGoal("t", GOAL_ID, { title: "x" }).catch(
      (e: unknown) => e,
    )) as ApiError;

    expect(error.fieldErrors).toEqual({
      learning_preferences: "Not one of the choices",
      preferred_languages: "Choose from: en, hi, or.",
    });
  });
});

describe("document calls", () => {
  const DOC_ID = "99999999-9999-4999-8999-999999999999";

  it("uploads the raw file as the body, with its name in the query and the token in a header", async () => {
    const fetchMock = vi.fn<(input: URL | string, init?: RequestInit) => Promise<Response>>(
      async () => json({ id: DOC_ID }, 202),
    );
    vi.stubGlobal("fetch", fetchMock);
    const file = new File(["Ownership means one owner."], "notes.txt", { type: "text/plain" });

    const created = await uploadDocument("access-token-123", GOAL_ID, file, "Chapter 1");

    expect(created).toEqual({ id: DOC_ID });
    const [url, init] = fetchMock.mock.calls[0] ?? [];
    const target = new URL(String(url));
    expect(target.pathname).toBe(`/v1/goals/${GOAL_ID}/documents`);
    expect(target.searchParams.get("name")).toBe("notes.txt");
    expect(target.searchParams.get("title")).toBe("Chapter 1");
    expect(target.search).not.toContain("access-token");
    expect(init?.method).toBe("POST");
    expect(init?.body).toBe(file);
    expect(init?.headers).toMatchObject({
      Authorization: "Bearer access-token-123",
      "Content-Type": "application/octet-stream",
    });
  });

  it("turns a refused upload into an error with the API's reason", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        problem(413, { code: "FILE_TOO_LARGE", detail: "That file is larger than 10 MB." }),
      ),
    );

    const error = (await uploadDocument("t", GOAL_ID, new File(["x"], "a.txt"), null).catch(
      (e: unknown) => e,
    )) as ApiError;

    expect(error).toBeInstanceOf(ApiError);
    expect([error.status, error.code, error.message]).toEqual([
      413,
      "FILE_TOO_LARGE",
      "That file is larger than 10 MB.",
    ]);
  });

  it("reports an unreachable service instead of throwing a network error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("fetch failed");
      }),
    );

    await expect(
      uploadDocument("t", GOAL_ID, new File(["x"], "a.txt"), null),
    ).rejects.toMatchObject({
      status: 0,
      code: "API_UNREACHABLE",
    });
  });

  it("searches with a body that names no owner", async () => {
    const fetchMock = stubFetch(() =>
      json({ items: [], enough_evidence: false, searched_documents: 0 }),
    );

    await searchDocuments("t", GOAL_ID, { query: "ownership" });

    const request = fetchMock.mock.calls[0]?.[0] as Request;
    expect(request.method).toBe("POST");
    expect(new URL(request.url).pathname).toBe(`/v1/goals/${GOAL_ID}/documents/search`);
    expect(await request.json()).toEqual({ query: "ownership" });
  });

  it("asks for a document's file through the API, never a storage link", async () => {
    const fetchMock = vi.fn<(input: URL | string, init?: RequestInit) => Promise<Response>>(
      async () => new Response("bytes", { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const response = await downloadDocument("access-token-123", DOC_ID);

    expect(await response.text()).toBe("bytes");
    expect(new URL(String(fetchMock.mock.calls[0]?.[0])).pathname).toBe(
      `/v1/documents/${DOC_ID}/file`,
    );
  });
});
