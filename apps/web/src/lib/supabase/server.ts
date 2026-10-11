import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";
import { connection } from "next/server";

import { getSupabaseConfig } from "@/lib/env";
import { hardenAuthCookie, shouldUseSecureCookies } from "@/lib/supabase/cookies";

/**
 * A Supabase client bound to the current request's cookies (Server Components, Server Actions
 * and Route Handlers). Returns null when Supabase is not configured (development only).
 *
 * Always create a new client per request; never keep one in module scope.
 *
 * It waits for a real request first (`connection()`). Supabase's auth client starts loading the
 * session, and reads the clock, the moment it is constructed. Next only allows that once it knows
 * the render is per-request; without this, every page that reads the session logs a
 * "Date.now() while prerendering" error and Next may abandon the render it was building.
 */
export async function createClient() {
  const config = getSupabaseConfig();
  if (!config) return null;

  await connection();
  const cookieStore = await cookies();
  const secure = shouldUseSecureCookies(config.url);

  return createServerClient(config.url, config.publishableKey, {
    cookies: {
      getAll() {
        return cookieStore.getAll();
      },
      setAll(cookiesToSet) {
        try {
          for (const { name, value, options } of cookiesToSet) {
            cookieStore.set(name, value, hardenAuthCookie(options, { secure }));
          }
        } catch {
          // Called from a Server Component, where cookies cannot be written. Safe to ignore:
          // the proxy refreshes the session and writes the cookies on every request.
        }
      },
    },
  });
}
