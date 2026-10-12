import { goalPath } from "@/lib/goals/ids";

/** A goal's study material: its documents, an upload form and a search. */
export const documentsPath = (goalId: string) => `${goalPath(goalId)}/documents`;

/** One document: its status, the text taken from it, and what can be done with it. */
export const documentPath = (goalId: string, documentId: string) =>
  `${documentsPath(goalId)}/${documentId}`;

/** The original file, as a download (served through the app, never as a public link). */
export const documentFilePath = (goalId: string, documentId: string) =>
  `${documentPath(goalId, documentId)}/file`;
