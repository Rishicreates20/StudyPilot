import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

import { isAuthCode, isProtectedPath, signInUrlFor } from "@/lib/auth/paths";
import { getSupabaseConfig } from "@/lib/env";
import { ONBOARDING_PATH } from "@/lib/onboarding/paths";
import { hardenAuthCookie, shouldUseSecureCookies } from "@/lib/supabase/cookies";

/**
 * Refreshes the Supabase session on every matched request and keeps the browser and server
 * cookies in sync, then applies the route-level redirects for signed-out visitors.
 *
 * This is a user-experience layer, NOT the security boundary: every protected page re-checks the
 * session on the server, and the API verifies the access token on every call.
 *
 * Rules from the Supabase SSR guide that must hold here:
 * - run nothing between createServerClient() and getClaims(), or users get logged out at random;
 * - return the `supabaseResponse` object the last setAll() built (it carries the new cookies and
 *   the cache headers that stop a CDN from caching one user's session for another).
 */
export async function updateSession(request: NextRequest): Promise<NextResponse> {
  const config = getSupabaseConfig();
  if (!config) return NextResponse.next({ request });

  // Supabase's built-in confirmation email lands on the Site URL (here, the landing page) with a
  // one-time `code`. Pass it to the route that turns it into a session, and start the new account
  // with the short setup. Nothing else about the request is trusted or forwarded.
  const landingCode = request.nextUrl.searchParams.get("code");
  if (request.nextUrl.pathname === "/" && isAuthCode(landingCode)) {
    const confirm = new URL("/auth/confirm", request.url);
    confirm.searchParams.set("code", landingCode);
    confirm.searchParams.set("next", ONBOARDING_PATH);
    return NextResponse.redirect(confirm);
  }

  let supabaseResponse = NextResponse.next({ request });
  const secure = shouldUseSecureCookies(config.url);

  const supabase = createServerClient(config.url, config.publishableKey, {
    cookies: {
      getAll() {
        return request.cookies.getAll();
      },
      setAll(cookiesToSet, headers) {
        for (const { name, value } of cookiesToSet) request.cookies.set(name, value);
        supabaseResponse = NextResponse.next({ request });
        for (const { name, value, options } of cookiesToSet) {
          supabaseResponse.cookies.set(name, value, hardenAuthCookie(options, { secure }));
        }
        for (const [key, value] of Object.entries(headers)) {
          supabaseResponse.headers.set(key, value);
        }
      },
    },
  });

  // Verifies the token's signature (it does not just read the cookie) and refreshes it if needed.
  const { data } = await supabase.auth.getClaims();
  const signedIn = Boolean(data?.claims?.sub);
  const { pathname, search } = request.nextUrl;

  if (!signedIn && isProtectedPath(pathname)) {
    const redirect = NextResponse.redirect(new URL(signInUrlFor(pathname + search), request.url));
    // Keep any cookies the failed refresh attempt cleared.
    for (const cookie of supabaseResponse.cookies.getAll()) redirect.cookies.set(cookie);
    return redirect;
  }

  return supabaseResponse;
}
