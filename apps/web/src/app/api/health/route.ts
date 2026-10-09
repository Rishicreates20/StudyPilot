import { connection } from "next/server";

import pkg from "../../../../package.json";
import { siteName } from "@/lib/site";

/**
 * Liveness probe for the web app (used by Docker and hosting health checks).
 *
 * `connection()` opts this handler out of build-time prerendering so every call reports on the
 * running process instead of replaying a response frozen at build time.
 */
export async function GET() {
  await connection();
  return Response.json(
    {
      status: "ok",
      service: `${siteName} web`,
      version: pkg.version,
      uptimeSeconds: Math.round(process.uptime()),
    },
    { headers: { "Cache-Control": "no-store" } },
  );
}
