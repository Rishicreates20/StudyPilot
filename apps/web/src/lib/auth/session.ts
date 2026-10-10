import { redirect } from "next/navigation";

import { signInUrlFor } from "@/lib/auth/paths";
import { createClient } from "@/lib/supabase/server";

export type SessionUser = {
  readonly id: string;
  readonly email: string | null;
};

/**
 * The signed-in user for this request, or null.
 *
 * Uses `getClaims()`, which verifies the token's signature. It never trusts the session cookie
 * as-is: anyone can forge a cookie, and `getSession()` would read it back without checking.
 */
export async function getSessionUser(): Promise<SessionUser | null> {
  const supabase = await createClient();
  if (!supabase) return null;

  const { data, error } = await supabase.auth.getClaims();
  const claims = data?.claims;
  if (error || !claims?.sub) return null;

  const email = typeof claims.email === "string" ? claims.email : null;
  return { id: claims.sub, email };
}

/** For protected pages: the signed-in user, or a redirect to sign-in that returns here after. */
export async function requireSessionUser(returnTo: string): Promise<SessionUser> {
  const user = await getSessionUser();
  if (!user) redirect(signInUrlFor(returnTo));
  return user;
}

/** A signed-in user together with the token to call the API on their behalf. */
export async function requireApiSession(
  returnTo: string,
): Promise<{ user: SessionUser; accessToken: string }> {
  const user = await requireSessionUser(returnTo);
  const accessToken = await getAccessToken();
  if (!accessToken) redirect(signInUrlFor(returnTo));
  return { user, accessToken };
}

/**
 * The access token to send to the API as `Authorization: Bearer`. Call it only after
 * `requireSessionUser()`.
 *
 * Reading the token from the session is fine here because the API (not this app) is the one that
 * verifies it, on every request. The session's `user` object is never used for decisions.
 */
export async function getAccessToken(): Promise<string | null> {
  const supabase = await createClient();
  if (!supabase) return null;
  const { data } = await supabase.auth.getSession();
  return data.session?.access_token ?? null;
}
