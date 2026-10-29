import type { ApiError } from "@/lib/api/server";

/** Which notice explains why the API refused an export request or a deletion. */
export function noticeForExportRefusal(error: ApiError): string {
  switch (error.code) {
    case "GOAL_ARCHIVED":
      return "export-goal-archived";
    case "EXPORT_ALLOWANCE_USED":
      return "export-limit-today";
    case "EXPORT_BUSY":
      return "export-busy";
    case "EXPORT_NOT_READY":
      return "export-not-ready";
    case "STORAGE_NOT_CONFIGURED":
    case "STORAGE_UNAVAILABLE":
    case "STORAGE_FORBIDDEN":
    case "STORAGE_REJECTED":
    case "FILE_MISSING":
      return "storage-unavailable";
    default:
      return "unavailable";
  }
}

/** The notice after a successful request: made just now, or already there. */
export function noticeForRequested(status: string): string {
  return status === "ready" ? "export-ready" : "export-requested";
}
