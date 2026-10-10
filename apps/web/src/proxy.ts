import type { NextRequest } from "next/server";

import { updateSession } from "@/lib/supabase/proxy";

/** Next.js 16 request interceptor (the file formerly named middleware.ts). */
export async function proxy(request: NextRequest) {
  return updateSession(request);
}

export const config = {
  matcher: [
    // Everything except static assets, metadata files and the web health probe.
    "/((?!_next/static|_next/image|api/health|icon.svg|robots.txt|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)",
  ],
};
