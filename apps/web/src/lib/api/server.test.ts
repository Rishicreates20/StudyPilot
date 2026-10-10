// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, createGoal, fetchGoals, fetchMe } from "@/lib/api/server";

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
