// @vitest-environment node
import { describe, expect, it, vi } from "vitest";

import { GET } from "@/app/api/health/route";

// `connection()` only means something inside a Next.js request; in unit tests it is a no-op.
vi.mock("next/server", () => ({ connection: async () => {} }));

describe("GET /api/health", () => {
  it("reports liveness, version and uptime without caching", async () => {
    const response = await GET();
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(response.headers.get("Cache-Control")).toBe("no-store");
    expect(body).toMatchObject({ status: "ok", version: "0.1.0" });
    expect(body.service).toContain("web");
    expect(body.uptimeSeconds).toBeGreaterThanOrEqual(0);
  });
});
