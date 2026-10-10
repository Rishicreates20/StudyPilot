/**
 * Where users go before and after authentication, and which routes need a session.
 *
 * Pure functions with no framework imports, so they are shared by the proxy, server actions and
 * route handlers, and are easy to test.
 */

export const SIGN_IN_PATH = "/sign-in";
export const SIGN_UP_PATH = "/sign-up";
export const DASHBOARD_PATH = "/dashboard";

const PROTECTED_PREFIXES = ["/dashboard", "/goals"] as const;

export function isProtectedPath(pathname: string): boolean {
  return PROTECTED_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
}

/**
 * Accept only same-site, path-only destinations ("/dashboard", "/goals/new?x=1").
 *
 * Everything else collapses to `fallback`. This closes the open-redirect hole in "go to ?next="
 * flows: absolute URLs, protocol-relative ("//evil.example"), backslash tricks ("/\evil.example"),
 * and control characters are all refused.
 */
export function safeRedirectPath(candidate: unknown, fallback: string = DASHBOARD_PATH): string {
  if (typeof candidate !== "string" || candidate.length === 0 || candidate.length > 500) {
    return fallback;
  }
  if (!candidate.startsWith("/") || candidate.startsWith("//") || candidate.includes("\\")) {
    return fallback;
  }
  // Control characters (CR/LF/tab...) can be used to smuggle headers or confuse parsers.
  if (/[\u0000-\u001f\u007f]/.test(candidate)) return fallback;
  try {
    // Resolving against a fake origin proves the result cannot leave this site.
    const resolved = new URL(candidate, "http://studypilot.invalid");
    if (resolved.origin !== "http://studypilot.invalid") return fallback;
  } catch {
    return fallback;
  }
  return candidate;
}

export function signInUrlFor(destination: string): string {
  const next = safeRedirectPath(destination, DASHBOARD_PATH);
  return `${SIGN_IN_PATH}?next=${encodeURIComponent(next)}`;
}

/** The `error` value of a sign-in URL that was reached because the API refused the session. */
export const SESSION_ENDED_ERROR = "session_ended";

/**
 * Sign-in after the API REFUSED a session that Supabase still considers valid (for example the
 * account was deleted, or the token is no longer acceptable). The sign-in page must show its form
 * for this URL instead of redirecting a "signed-in" visitor away, or the two pages would send the
 * visitor back and forth forever.
 */
export function sessionEndedUrlFor(destination: string): string {
  return `${signInUrlFor(destination)}&error=${SESSION_ENDED_ERROR}`;
}
