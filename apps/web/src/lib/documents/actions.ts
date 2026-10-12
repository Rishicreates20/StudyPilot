"use server";

import { revalidatePath } from "next/cache";
import { notFound, redirect } from "next/navigation";

import { failureMessage } from "@/lib/api/failure";
import {
  ApiError,
  cancelJob,
  confirmDocument,
  deleteDocument,
  editDocumentPage,
  pasteDocument,
  reprocessDocument,
  renameDocument,
  searchDocuments,
  uploadDocument,
} from "@/lib/api/server";
import { requireSession } from "@/lib/auth/action-session";
import { sessionEndedUrlFor } from "@/lib/auth/paths";
import { documentPath, documentsPath } from "@/lib/documents/paths";
import {
  pageFormSchema,
  pasteFormSchema,
  renameFormSchema,
  searchFormSchema,
  uploadFormSchema,
  type PageFormState,
  type PasteFormState,
  type RenameFormState,
  type SearchState,
  type UploadFormState,
} from "@/lib/documents/schema";
import { formString, zodFieldErrors } from "@/lib/forms";
import { isGoalId } from "@/lib/goals/ids";

/**
 * Adding, checking, processing again, searching and deleting study documents.
 *
 * The rules are the same as everywhere else: nothing here names an owner (the API derives it from
 * the verified token and answers 404 for anything that is not the caller's), identifiers from the
 * browser are checked before they reach an API path, and a failed form returns a message instead
 * of throwing. What a file *is* is decided by the API from its bytes; the browser's claim about
 * its name or type is never trusted. Reading and indexing happen later, in the worker.
 */

/** API codes that describe the chosen file, so they belong next to the file input. */
function isFileProblem(error: ApiError): boolean {
  return (
    error.status === 413 ||
    error.status === 415 ||
    error.code === "FILE_EMPTY" ||
    error.code === "DOCUMENT_EXISTS"
  );
}

/** Which notice explains why the API refused a change to a document. */
function noticeForRefusal(error: ApiError): string {
  switch (error.code) {
    case "DOCUMENT_BUSY":
      return "document-busy";
    case "GOAL_ARCHIVED":
      return "goal-archived";
    case "NOTHING_TO_CONFIRM":
      return "nothing-to-confirm";
    case "DOCUMENT_LIMIT_REACHED_TODAY":
      return "document-limit-today";
    case "STORAGE_NOT_CONFIGURED":
    case "STORAGE_UNAVAILABLE":
    case "FILE_MISSING":
      return "storage-unavailable";
    case "AI_NOT_CONFIGURED":
      return "documents-ai-unavailable";
    default:
      return error.status === 409 ? "status-conflict" : "unavailable";
  }
}

function checkIds(...ids: string[]): void {
  if (!ids.every(isGoalId)) notFound();
}

function withNotice(path: string, notice: string): string {
  return `${path}?notice=${notice}`;
}

/** Add a file. Bound to the goal by the page: `uploadDocumentAction.bind(null, goalId)`. */
export async function uploadDocumentAction(
  goalId: string,
  _previous: UploadFormState,
  formData: FormData,
): Promise<UploadFormState> {
  checkIds(goalId);
  const values = { title: formString(formData, "title") };
  const parsed = uploadFormSchema.safeParse(values);
  const fieldErrors: Partial<Record<"file" | "title", string>> = parsed.success
    ? {}
    : zodFieldErrors<"file" | "title">(parsed.error);
  const file = formData.get("file");
  if (!(file instanceof File) || file.size === 0) fieldErrors.file = "Choose a file to upload.";
  if (!parsed.success || !(file instanceof File) || file.size === 0) {
    return { status: "error", fieldErrors, values };
  }

  const { accessToken } = await requireSession(documentsPath(goalId));
  let created;
  try {
    created = await uploadDocument(accessToken, goalId, file, parsed.data.title || null);
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    if (error.isUnauthenticated) redirect(sessionEndedUrlFor(documentsPath(goalId)));
    if (error.status === 404) notFound();
    const message = failureMessage(error, "document");
    return isFileProblem(error)
      ? { status: "error", fieldErrors: { file: error.message }, values }
      : { status: "error", formError: message, fieldErrors: {}, values };
  }
  redirect(documentPath(goalId, created.id));
}

/** Add pasted text. Bound to the goal by the page. */
export async function pasteDocumentAction(
  goalId: string,
  _previous: PasteFormState,
  formData: FormData,
): Promise<PasteFormState> {
  checkIds(goalId);
  const values = { title: formString(formData, "title"), text: formString(formData, "text") };
  const parsed = pasteFormSchema.safeParse(values);
  if (!parsed.success) {
    return { status: "error", fieldErrors: zodFieldErrors(parsed.error), values };
  }

  const { accessToken } = await requireSession(documentsPath(goalId));
  let created;
  try {
    created = await pasteDocument(accessToken, goalId, parsed.data);
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    if (error.isUnauthenticated) redirect(sessionEndedUrlFor(documentsPath(goalId)));
    if (error.status === 404) notFound();
    return {
      status: "error",
      formError: failureMessage(error, "material"),
      fieldErrors:
        error.status === 413 || error.code === "DOCUMENT_EXISTS" ? { text: error.message } : {},
      values,
    };
  }
  redirect(documentPath(goalId, created.id));
}

/** Rename a document. Bound to the goal and the document. */
export async function renameDocumentAction(
  goalId: string,
  documentId: string,
  _previous: RenameFormState,
  formData: FormData,
): Promise<RenameFormState> {
  checkIds(goalId, documentId);
  const values = { title: formString(formData, "title") };
  const parsed = renameFormSchema.safeParse(values);
  if (!parsed.success) {
    return { status: "error", fieldErrors: zodFieldErrors(parsed.error), values };
  }
  const { accessToken } = await requireSession(documentPath(goalId, documentId));
  try {
    const renamed = await renameDocument(accessToken, documentId, parsed.data.title);
    revalidatePath(documentPath(goalId, documentId));
    return { status: "success", message: "Title saved.", values: { title: renamed.title } };
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    if (error.isUnauthenticated) redirect(sessionEndedUrlFor(documentPath(goalId, documentId)));
    if (error.status === 404) notFound();
    return {
      status: "error",
      formError: failureMessage(error, "title"),
      fieldErrors: {},
      values,
    };
  }
}

/** Correct the text of one page that waits for review. Bound to the goal, document and page. */
export async function savePageAction(
  goalId: string,
  documentId: string,
  pageNumber: number,
  _previous: PageFormState,
  formData: FormData,
): Promise<PageFormState> {
  checkIds(goalId, documentId);
  if (!Number.isInteger(pageNumber) || pageNumber < 1 || pageNumber > 100_000) notFound();
  const values = { text: formString(formData, "text") };
  const parsed = pageFormSchema.safeParse(values);
  if (!parsed.success) {
    return { status: "error", fieldErrors: zodFieldErrors(parsed.error), values };
  }
  const { accessToken } = await requireSession(documentPath(goalId, documentId));
  try {
    const saved = await editDocumentPage(accessToken, documentId, pageNumber, parsed.data.text);
    revalidatePath(documentPath(goalId, documentId));
    return { status: "success", message: "Saved.", values: { text: saved.text } };
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    if (error.isUnauthenticated) redirect(sessionEndedUrlFor(documentPath(goalId, documentId)));
    if (error.status === 404 && error.code !== "PAGE_NOT_FOUND") notFound();
    return {
      status: "error",
      formError:
        error.status === 409
          ? "This document is no longer waiting for review, so its text can't be changed."
          : failureMessage(error, "text"),
      fieldErrors: {},
      values,
    };
  }
}

/** Use the extracted text as it stands: index it so it can be searched and cited. */
export async function confirmDocumentAction(goalId: string, documentId: string): Promise<void> {
  checkIds(goalId, documentId);
  const { accessToken } = await requireSession(documentPath(goalId, documentId));
  try {
    await confirmDocument(accessToken, documentId);
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    if (error.isUnauthenticated) redirect(sessionEndedUrlFor(documentPath(goalId, documentId)));
    if (error.status === 404) notFound();
    redirect(withNotice(documentPath(goalId, documentId), noticeForRefusal(error)));
  }
  redirect(documentPath(goalId, documentId));
}

/** Read the stored file again from scratch. */
export async function reprocessDocumentAction(goalId: string, documentId: string): Promise<void> {
  checkIds(goalId, documentId);
  const { accessToken } = await requireSession(documentPath(goalId, documentId));
  try {
    await reprocessDocument(accessToken, documentId);
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    if (error.isUnauthenticated) redirect(sessionEndedUrlFor(documentPath(goalId, documentId)));
    if (error.status === 404) notFound();
    redirect(withNotice(documentPath(goalId, documentId), noticeForRefusal(error)));
  }
  redirect(documentPath(goalId, documentId));
}

/** Ask a queued or running document job to stop. */
export async function cancelDocumentJobAction(
  goalId: string,
  documentId: string,
  jobId: string,
): Promise<void> {
  checkIds(goalId, documentId, jobId);
  const { accessToken } = await requireSession(documentPath(goalId, documentId));
  try {
    await cancelJob(accessToken, jobId);
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    if (error.isUnauthenticated) redirect(sessionEndedUrlFor(documentPath(goalId, documentId)));
    if (error.status === 404) notFound();
    redirect(withNotice(documentPath(goalId, documentId), noticeForRefusal(error)));
  }
  redirect(withNotice(documentPath(goalId, documentId), "document-cancelled"));
}

/** Delete a document: its file, its text and its indexed passages. */
export async function deleteDocumentAction(goalId: string, documentId: string): Promise<void> {
  checkIds(goalId, documentId);
  const { accessToken } = await requireSession(documentPath(goalId, documentId));
  try {
    await deleteDocument(accessToken, documentId);
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    if (error.isUnauthenticated) redirect(sessionEndedUrlFor(documentPath(goalId, documentId)));
    if (error.status === 404) notFound();
    redirect(withNotice(documentPath(goalId, documentId), noticeForRefusal(error)));
  }
  redirect(withNotice(documentsPath(goalId), "document-deleted"));
}

/** Search the goal's documents. Bound to the goal. Returns the passages found (possibly none). */
export async function searchDocumentsAction(
  goalId: string,
  _previous: SearchState,
  formData: FormData,
): Promise<SearchState> {
  checkIds(goalId);
  const query = formString(formData, "query");
  const parsed = searchFormSchema.safeParse({ query });
  if (!parsed.success) {
    return {
      status: "error",
      message: parsed.error.issues[0]?.message ?? "Type a question or a few words.",
      query,
    };
  }
  const { accessToken } = await requireSession(documentsPath(goalId));
  try {
    const result = await searchDocuments(accessToken, goalId, { query: parsed.data.query });
    return { status: "results", query: parsed.data.query, result };
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    if (error.isUnauthenticated) redirect(sessionEndedUrlFor(documentsPath(goalId)));
    if (error.status === 404) notFound();
    return {
      status: "error",
      message:
        error.code === "SEARCH_RATE_LIMITED"
          ? "You're searching very quickly. Please wait a moment and try again."
          : error.status === 503 || error.status === 0
            ? "Search isn't available right now. Please try again in a moment."
            : failureMessage(error, "search"),
      query: parsed.data.query,
    };
  }
}
