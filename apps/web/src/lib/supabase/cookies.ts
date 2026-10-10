import type { CookieOptions } from "@supabase/ssr";

/**
 * Hardening for the cookies that carry the Supabase session.
 *
 * `@supabase/ssr` defaults to script-readable cookies (`httpOnly: false`) because its *browser*
 * client has to read them. This app never creates a browser client: sessions are read and
 * refreshed only on the server (Server Components, Server Actions, the proxy). So the cookies can
 * be HttpOnly, which means a cross-site-scripting bug cannot read the access or refresh token.
 *
 * Do not add `createBrowserClient` anywhere without revisiting this: it would stop working.
 */
export function hardenAuthCookie(
  options: CookieOptions | undefined,
  { secure }: { secure: boolean },
): CookieOptions {
  return { ...options, httpOnly: true, sameSite: "lax", secure };
}

/**
 * Mark cookies `Secure` in real deployments only. A production build talking to an https Supabase
 * project is a deployment; local development and the CI browser tests (a production build against
 * a plain-http local stack) stay usable over http, where some browsers drop Secure cookies.
 */
export function shouldUseSecureCookies(supabaseUrl: string): boolean {
  return process.env.NODE_ENV === "production" && supabaseUrl.startsWith("https://");
}
