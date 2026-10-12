import { connection } from "next/server";

import { ApiError, downloadDocument } from "@/lib/api/server";
import { sessionEndedUrlFor, signInUrlFor } from "@/lib/auth/paths";
import { getAccessToken, getSessionUser } from "@/lib/auth/session";
import { documentFilePath } from "@/lib/documents/paths";
import { isGoalId } from "@/lib/goals/ids";

type Context = { params: Promise<{ id: string; documentId: string }> };

/**
 * The original file of a document, as a download. The browser never gets a storage link: this
 * route asks the API for the bytes as the signed-in user (the API checks the document is theirs)
 * and passes them on as an attachment that is never displayed inline or sniffed as another type.
 */
export async function GET(request: Request, { params }: Context): Promise<Response> {
  await connection(); // a download is per user and per request
  const { id, documentId } = await params;
  if (!isGoalId(id) || !isGoalId(documentId)) return new Response("Not found", { status: 404 });

  const returnTo = documentFilePath(id, documentId);
  const user = await getSessionUser();
  const accessToken = user ? await getAccessToken() : null;
  if (!accessToken) return Response.redirect(new URL(signInUrlFor(returnTo), request.url), 303);

  let upstream: Response;
  try {
    upstream = await downloadDocument(accessToken, documentId);
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    if (error.isUnauthenticated) {
      return Response.redirect(new URL(sessionEndedUrlFor(returnTo), request.url), 303);
    }
    if (error.status === 404) return new Response("Not found", { status: 404 });
    return new Response("The file can't be downloaded right now. Please try again.", {
      status: 502,
    });
  }

  return new Response(upstream.body, {
    headers: {
      "Content-Type": "application/octet-stream",
      "Content-Disposition": upstream.headers.get("content-disposition") ?? "attachment",
      "X-Content-Type-Options": "nosniff",
      "Cache-Control": "private, no-store",
    },
  });
}
