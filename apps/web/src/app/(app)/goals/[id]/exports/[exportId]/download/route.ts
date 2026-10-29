import { connection } from "next/server";

import { ApiError, createDownloadLink, downloadExportFile } from "@/lib/api/server";
import { sessionEndedUrlFor, signInUrlFor } from "@/lib/auth/paths";
import { getAccessToken, getSessionUser } from "@/lib/auth/session";
import { getPublicEnv } from "@/lib/env";
import { isTrustedDownloadLink } from "@/lib/exports/download";
import { exportDownloadPath, exportsPath } from "@/lib/exports/paths";
import { isGoalId } from "@/lib/goals/ids";

type Context = { params: Promise<{ id: string; exportId: string }> };

/**
 * Downloads an exported file. The route asks the API, as the signed-in user, for a short-lived
 * signed link to that one file (the API checks the export is theirs and ready) and redirects the
 * browser to it. On a server that keeps files on its own disk there is no link: the route fetches
 * the bytes from the API and passes them on as an attachment, never displayed inline.
 */
export async function GET(request: Request, { params }: Context): Promise<Response> {
  await connection(); // a download is per user and per request
  const { id, exportId } = await params;
  if (!isGoalId(id) || !isGoalId(exportId)) return new Response("Not found", { status: 404 });

  const returnTo = exportDownloadPath(id, exportId);
  const user = await getSessionUser();
  const accessToken = user ? await getAccessToken() : null;
  if (!accessToken) return Response.redirect(new URL(signInUrlFor(returnTo), request.url), 303);

  try {
    const link = await createDownloadLink(accessToken, exportId);
    if (link.url !== null) {
      if (!isTrustedDownloadLink(link.url, getPublicEnv().NEXT_PUBLIC_SUPABASE_URL)) {
        return new Response("The file can't be downloaded right now. Please try again.", {
          status: 502,
        });
      }
      return new Response(null, {
        status: 303,
        headers: { Location: link.url, "Cache-Control": "private, no-store" },
      });
    }
    const upstream = await downloadExportFile(accessToken, exportId);
    return new Response(upstream.body, {
      headers: {
        "Content-Type": "application/octet-stream",
        "Content-Disposition": upstream.headers.get("content-disposition") ?? "attachment",
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-store",
      },
    });
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    if (error.isUnauthenticated) {
      return Response.redirect(new URL(sessionEndedUrlFor(returnTo), request.url), 303);
    }
    if (error.status === 404) return new Response("Not found", { status: 404 });
    if (error.code === "EXPORT_NOT_READY") {
      return Response.redirect(
        new URL(`${exportsPath(id)}?notice=export-not-ready`, request.url),
        303,
      );
    }
    return new Response("The file can't be downloaded right now. Please try again.", {
      status: 502,
    });
  }
}
