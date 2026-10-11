import { notFound, redirect } from "next/navigation";

import { ApiError } from "@/lib/api/server";
import { sessionEndedUrlFor } from "@/lib/auth/paths";
import { requireApiSession } from "@/lib/auth/session";

/**
 * Run an API call for a page, as the signed-in user, with the two failures every page handles the
 * same way:
 *
 * - the API refuses the session (expired, revoked, account deleted): back to sign-in, with the
 *   marker that shows the form instead of looping (see `sessionEndedUrlFor`);
 * - the resource is not found, or is not the caller's (the API answers 404 for both): the
 *   not-found page.
 *
 * Anything else is rethrown for the caller (or the error boundary) to present.
 */
export async function callApi<T>(
  returnTo: string,
  run: (accessToken: string) => Promise<T>,
): Promise<T> {
  const { accessToken } = await requireApiSession(returnTo);
  try {
    return await run(accessToken);
  } catch (error) {
    if (error instanceof ApiError) {
      if (error.isUnauthenticated) redirect(sessionEndedUrlFor(returnTo));
      if (error.status === 404) notFound();
    }
    throw error;
  }
}
