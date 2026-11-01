// @vitest-environment node
import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api/server";
import { isTrustedDownloadLink } from "@/lib/exports/download";
import {
  FORMAT_LABELS,
  LESSON_FORMATS,
  ROADMAP_FORMATS,
  STATUS_LABELS,
  anyProcessing,
  describeExportStage,
  isLessonFormat,
  isRoadmapFormat,
  pagesLabel,
} from "@/lib/exports/labels";
import { exportDownloadPath, exportsPath } from "@/lib/exports/paths";
import { noticeForExportRefusal, noticeForRequested } from "@/lib/exports/refusals";
import { noticeFor } from "@/lib/goals/notices";
import { EXPORT, GOAL, exportItem } from "@/test-support/exports";

describe("export formats", () => {
  it("offers notes, a revision sheet and slides for a lesson, and a roadmap PDF and slides for a roadmap", () => {
    expect(LESSON_FORMATS).toEqual(["notes_pdf", "revision_pdf", "slides_pptx"]);
    expect(ROADMAP_FORMATS).toEqual(["roadmap_pdf", "slides_pptx"]);
    for (const format of [...LESSON_FORMATS, ...ROADMAP_FORMATS]) {
      expect(FORMAT_LABELS[format].title).not.toBe("");
      expect(FORMAT_LABELS[format].detail).not.toBe("");
    }
  });

  it("accepts only a format that fits the source", () => {
    expect(isLessonFormat("notes_pdf")).toBe(true);
    expect(isLessonFormat("slides_pptx")).toBe(true);
    expect(isLessonFormat("roadmap_pdf")).toBe(false);
    expect(isRoadmapFormat("roadmap_pdf")).toBe(true);
    expect(isRoadmapFormat("notes_pdf")).toBe(false);
    expect(isRoadmapFormat("revision_pdf")).toBe(false);
  });

  it.each([null, undefined, "", "NOTES_PDF", "notes_pdf ", "docx", 1, new File([], "notes_pdf")])(
    "refuses %s as a format",
    (value) => {
      expect(isLessonFormat(value)).toBe(false);
      expect(isRoadmapFormat(value)).toBe(false);
    },
  );
});

describe("export labels", () => {
  it("names every status in words", () => {
    expect(STATUS_LABELS).toEqual({
      ready: "Ready to download",
      processing: "Being made",
      failed: "Couldn't be made",
      not_started: "Not made yet",
    });
  });

  it("describes the worker's stages, and an unknown stage generically", () => {
    expect(describeExportStage("rendering")).toBe("Laying out the file");
    expect(describeExportStage("waiting_retry")).toBe("Waiting to try again");
    expect(describeExportStage("something_new")).toBe("Working");
  });

  it("counts pages for a PDF and slides for a deck, singular for one", () => {
    expect(pagesLabel(exportItem({ page_count: 12 }))).toBe("12 pages");
    expect(pagesLabel(exportItem({ page_count: 1 }))).toBe("1 page");
    expect(pagesLabel(exportItem({ format: "slides_pptx", page_count: 1 }))).toBe("1 slide");
    expect(pagesLabel(exportItem({ format: "slides_pptx", page_count: 9 }))).toBe("9 slides");
    expect(pagesLabel(exportItem({ page_count: null }))).toBeNull();
  });

  it("knows when the list should keep refreshing itself", () => {
    expect(anyProcessing([])).toBe(false);
    expect(anyProcessing([{ status: "ready" }, { status: "failed" }])).toBe(false);
    expect(anyProcessing([{ status: "ready" }, { status: "processing" }])).toBe(true);
  });
});

describe("export paths", () => {
  it("lives under the goal", () => {
    expect(exportsPath(GOAL)).toBe(`/goals/${GOAL}/exports`);
    expect(exportDownloadPath(GOAL, EXPORT)).toBe(`/goals/${GOAL}/exports/${EXPORT}/download`);
  });
});

describe("export notices", () => {
  const refusal = (code: string, status = 409) => new ApiError(status, code, "x");

  it.each([
    ["GOAL_ARCHIVED", "export-goal-archived"],
    ["EXPORT_ALLOWANCE_USED", "export-limit-today"],
    ["EXPORT_BUSY", "export-busy"],
    ["EXPORT_NOT_READY", "export-not-ready"],
    ["STORAGE_NOT_CONFIGURED", "storage-unavailable"],
    ["STORAGE_UNAVAILABLE", "storage-unavailable"],
    ["STORAGE_FORBIDDEN", "storage-unavailable"],
    ["STORAGE_REJECTED", "storage-unavailable"],
    ["FILE_MISSING", "storage-unavailable"],
    ["SOMETHING_ELSE", "unavailable"],
  ])("explains %s with the %s notice", (code, notice) => {
    expect(noticeForExportRefusal(refusal(code))).toBe(notice);
  });

  it("says whether the file was asked for or already made", () => {
    expect(noticeForRequested("processing")).toBe("export-requested");
    expect(noticeForRequested("ready")).toBe("export-ready");
  });

  it.each([
    "export-requested",
    "export-ready",
    "export-busy",
    "export-deleted",
    "export-limit-today",
    "export-goal-archived",
    "export-not-ready",
    "storage-unavailable",
    "unavailable",
  ])("has fixed wording for %s (never text from the URL)", (code) => {
    expect(noticeFor(code)?.title).toBeTruthy();
  });
});

describe("isTrustedDownloadLink", () => {
  const SUPABASE = "https://abc.supabase.co";
  const SIGNED = `${SUPABASE}/storage/v1/object/sign/exports/u/e/notes_pdf.pdf?token=t&download=a.pdf`;

  it("follows a signed link to this project's exports bucket", () => {
    expect(isTrustedDownloadLink(SIGNED, SUPABASE)).toBe(true);
  });

  it("allows plain http only for a local Supabase", () => {
    const local = "http://127.0.0.1:54321";
    expect(
      isTrustedDownloadLink(`${local}/storage/v1/object/sign/exports/u/e/x.pdf?token=t`, local),
    ).toBe(true);
    expect(
      isTrustedDownloadLink(
        "http://abc.supabase.co/storage/v1/object/sign/exports/u/e/x.pdf",
        "http://abc.supabase.co",
      ),
    ).toBe(false);
  });

  it.each([
    ["another site", "https://evil.example/storage/v1/object/sign/exports/x.pdf"],
    ["another Supabase project", "https://other.supabase.co/storage/v1/object/sign/exports/x.pdf"],
    ["a look-alike host", "https://abc.supabase.co.evil.example/storage/v1/object/sign/exports/x"],
    ["another port", "https://abc.supabase.co:8443/storage/v1/object/sign/exports/x.pdf"],
    ["another bucket", `${SUPABASE}/storage/v1/object/sign/documents/u/d/notes.pdf?token=t`],
    ["a public object", `${SUPABASE}/storage/v1/object/public/exports/u/e/x.pdf`],
    ["a path that climbs out", `${SUPABASE}/storage/v1/object/sign/exports/../documents/x.pdf`],
    ["an encoded climb", `${SUPABASE}/storage/v1/object/sign/exports/%2e%2e/documents/x.pdf`],
    ["a javascript: link", "javascript:alert(1)"],
    ["a relative link", "/storage/v1/object/sign/exports/x.pdf"],
    ["something unparsable", "not a url"],
  ])("refuses %s", (_name, link) => {
    expect(isTrustedDownloadLink(link, SUPABASE)).toBe(false);
  });

  it("refuses everything when Supabase is not configured", () => {
    expect(isTrustedDownloadLink(SIGNED, undefined)).toBe(false);
    expect(isTrustedDownloadLink(SIGNED, "")).toBe(false);
    expect(isTrustedDownloadLink(SIGNED, "not a url")).toBe(false);
  });
});
