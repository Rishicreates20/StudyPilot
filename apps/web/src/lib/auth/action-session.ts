import { redirect } from "next/navigation";

import { signInUrlFor } from "@/lib/auth/paths";
import { getAccessToken, getSessionUser } from "@/lib/auth/session";

/**
 * For Server Actions: the access token of the signed-in user, or a redirect to sign-in that
 * returns to `returnTo` afterwards. Identity is decided by the API from this token; nothing a
 * browser sends in the action's arguments names an owner.
 */
export async function requireSession(returnTo: string): Promise<{ accessToken: string }> {
  const user = await getSessionUser();
  const accessToken = user ? await getAccessToken() : null;
  if (!accessToken) redirect(signInUrlFor(returnTo));
  return { accessToken };
}
