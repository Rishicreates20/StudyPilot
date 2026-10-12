import { FileTextIcon } from "lucide-react";
import Link from "next/link";
import { redirect } from "next/navigation";
import { connection } from "next/server";

import { AutoRefresh } from "@/components/documents/auto-refresh";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, fetchDocuments, type GoalStatus } from "@/lib/api/server";
import { sessionEndedUrlFor } from "@/lib/auth/paths";
import { requireApiSession } from "@/lib/auth/session";
import { documentsPath } from "@/lib/documents/paths";
import { anyWorking } from "@/lib/documents/state";
import { goalPath } from "@/lib/goals/ids";

export function DocumentsSectionSkeleton() {
  return (
    <div className="space-y-4" role="status" aria-label="Loading the study material">
      <Skeleton className="h-7 w-40" />
      <Skeleton className="h-24 w-full" />
    </div>
  );
}

/**
 * The goal page's study material summary: how many documents there are and a way in. Loaded on its
 * own so the goal appears first; if it can't be loaded it says so in a line instead of taking the
 * page down (the roadmap and progress do not depend on it).
 */
export async function DocumentsSection({
  goalId,
  goalStatus,
}: {
  goalId: string;
  goalStatus: GoalStatus;
}) {
  await connection();
  const { accessToken } = await requireApiSession(goalPath(goalId));
  let list;
  try {
    list = await fetchDocuments(accessToken, goalId);
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    if (error.isUnauthenticated) redirect(sessionEndedUrlFor(goalPath(goalId)));
    return (
      <section aria-labelledby="material-heading" className="space-y-2">
        <h2 id="material-heading" className="font-heading text-xl font-semibold tracking-tight">
          Study material
        </h2>
        <p className="text-sm text-muted-foreground">
          Your documents couldn&rsquo;t be loaded just now.{" "}
          <Link href={documentsPath(goalId)} className="underline underline-offset-4">
            Open study material
          </Link>
        </p>
      </section>
    );
  }

  const total = list.items.length;
  const ready = list.items.filter((document) => document.status === "ready").length;
  const waiting = list.items.filter((document) => document.status === "review").length;

  return (
    <section aria-labelledby="material-heading" className="space-y-3">
      {anyWorking(list.items) ? <AutoRefresh /> : null}
      <h2 id="material-heading" className="font-heading text-xl font-semibold tracking-tight">
        Study material
      </h2>
      <div className="flex flex-col gap-4 rounded-xl border bg-card p-5 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-start gap-3">
          <FileTextIcon className="mt-0.5 size-5 shrink-0 text-primary" aria-hidden="true" />
          <p className="text-sm leading-6">
            {total === 0 ? (
              <>
                Add your notes, a textbook chapter or a PDF, and this goal&rsquo;s lessons will be
                written from them whenever they cover a topic.
              </>
            ) : (
              <>
                {total === 1 ? "1 document" : `${total} documents`}
                {ready > 0 ? `, ${ready} ready to use` : ""}
                {waiting > 0 ? `, ${waiting} waiting for you to check its text` : ""}. Lessons draw
                on the ready ones.
              </>
            )}
          </p>
        </div>
        <Button asChild variant={total === 0 && goalStatus !== "archived" ? "default" : "outline"}>
          <Link href={documentsPath(goalId)}>
            {total === 0 && goalStatus !== "archived"
              ? "Add study material"
              : "Manage study material"}
          </Link>
        </Button>
      </div>
    </section>
  );
}
