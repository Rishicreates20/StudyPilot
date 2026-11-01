import { goalPath } from "@/lib/goals/ids";

/** A goal's exported files: PDF notes, revision sheets, roadmaps and slides. */
export const exportsPath = (goalId: string) => `${goalPath(goalId)}/exports`;

/**
 * Downloads one export. Served through the app: the route asks the API (as the signed-in user)
 * for a short-lived signed link and redirects to it, so the browser never holds a lasting link.
 */
export const exportDownloadPath = (goalId: string, exportId: string) =>
  `${exportsPath(goalId)}/${exportId}/download`;
