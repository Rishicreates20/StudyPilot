import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";

import { getSupabaseConfig } from "@/lib/env";
import { hardenAuthCookie, shouldUseSecureCookies } from "@/lib/supabase/cookies";

/**
 * A Supabase client bound to the current request's cookies (Server Components, Server Actions
 * and Route Handlers). Returns null when Supabase is not configured (development only).
 *
 * Always create a new client per request; never keep one in module scope.
 */
export async function createClient() {
  const config = getSupabaseConfig();
  if (!config) return null;

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
