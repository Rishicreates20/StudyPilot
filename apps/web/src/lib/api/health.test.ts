// @vitest-environment node
import { describe, expect, it, vi } from "vitest";

import { fetchApiStatus } from "@/lib/api/health";

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });

const healthy = { status: "ok", service: "StudyPilot", version: "0.1.0" };

function fakeApi(handlers: Record<string, () => Response | Promise<Response>>) {
  return vi.fn(async (input: string) => {
    const path = new URL(input).pathname;
    const handler = handlers[path];
    if (!handler) throw new Error(`unexpected request to ${path}`);
    return handler();
  });
}

describe("fetchApiStatus", () => {
  it("reports a ready API with its version", async () => {
    const fetcher = fakeApi({
      "/healthz": () => json(healthy),
      "/readyz": () => json({ status: "ready", checks: {} }),
    });

    const status = await fetchApiStatus(fetcher);

    expect(status).toMatchObject({ state: "up", version: "0.1.0", ready: true, checks: {} });
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("reports a live but not-ready API when a dependency check fails (HTTP 503)", async () => {
    const fetcher = fakeApi({
      "/healthz": () => json(healthy),
      "/readyz": () => json({ status: "unavailable", checks: { database: "fail" } }, 503),
    });

    const status = await fetchApiStatus(fetcher);

    expect(status).toMatchObject({ state: "up", ready: false, checks: { database: "fail" } });
  });

  it("reports unreachable on network failure instead of inventing a healthy answer", async () => {
    const fetcher = vi.fn(async () => {
      throw new TypeError("fetch failed");
    });

    expect(await fetchApiStatus(fetcher)).toEqual({ state: "unreachable", reason: "network" });
  });

  it("reports a timeout distinctly", async () => {
    const fetcher = vi.fn(async () => {
      throw new DOMException("The operation timed out.", "TimeoutError");
    });

    expect(await fetchApiStatus(fetcher)).toEqual({ state: "unreachable", reason: "timeout" });
  });

  it("rejects a response that is not a recognisable health payload", async () => {
    const fetcher = fakeApi({
      "/healthz": () => json({ hello: "world" }),
      "/readyz": () => json({ status: "ready", checks: {} }),
    });

    expect(await fetchApiStatus(fetcher)).toEqual({ state: "unreachable", reason: "bad-response" });
  });

  it("treats a non-JSON body as a bad response", async () => {
    const fetcher = fakeApi({
      "/healthz": () => new Response("<html>gateway error</html>", { status: 502 }),
      "/readyz": () => new Response("<html>gateway error</html>", { status: 502 }),
    });

    expect(await fetchApiStatus(fetcher)).toEqual({ state: "unreachable", reason: "bad-response" });
  });
});
