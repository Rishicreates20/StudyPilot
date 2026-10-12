import { describe, expect, it } from "vitest";

import {
  describeDocumentStage,
  documentKindLabel,
  documentStatusLabel,
  documentSummary,
  formatBytes,
  legibilityLabel,
  pageLabel,
  pluralize,
} from "@/lib/documents/labels";
import { documentFilePath, documentPath, documentsPath } from "@/lib/documents/paths";
import { anyWorking, documentPanelState } from "@/lib/documents/state";
import { DOC, GOAL, documentJob, studyDocument } from "@/test-support/documents";

describe("paths", () => {
  it("nests a document under its goal, and the file under the document", () => {
    expect(documentsPath(GOAL)).toBe(`/goals/${GOAL}/documents`);
    expect(documentPath(GOAL, DOC)).toBe(`/goals/${GOAL}/documents/${DOC}`);
    expect(documentFilePath(GOAL, DOC)).toBe(`/goals/${GOAL}/documents/${DOC}/file`);
  });
});

describe("labels", () => {
  it("formats sizes", () => {
    expect(formatBytes(1)).toBe("1 byte");
    expect(formatBytes(12)).toBe("12 bytes");
    expect(formatBytes(2048)).toBe("2 KB");
    expect(formatBytes(1_572_864)).toBe("1.5 MB");
  });

  it("pluralizes", () => {
    expect(pluralize(1, "page")).toBe("1 page");
    expect(pluralize(2, "page")).toBe("2 pages");
    expect(pluralize(0, "passage")).toBe("0 passages");
  });

  it("names statuses and kinds in plain words", () => {
    expect(documentStatusLabel("review")).toBe("Check the text");
    expect(documentStatusLabel("failed")).toBe("Couldn't process");
    expect(documentKindLabel("image")).toBe("Picture");
    expect(documentKindLabel("pasted")).toBe("Pasted text");
  });

  it("describes what a document is made of", () => {
    expect(documentSummary(studyDocument())).toBe("3 pages · 7 passages");
    expect(
      documentSummary(studyDocument({ paginated: false, page_count: 1, chunk_count: 0 })),
    ).toBe("1 part");
    expect(documentSummary(studyDocument({ page_count: null, chunk_count: 0 }))).toBe("");
  });

  it("calls a real page a page and a stretch of text a part", () => {
    expect(pageLabel(true, 3)).toBe("Page 3");
    expect(pageLabel(false, 3)).toBe("Part 3");
  });

  it("describes how legibly a picture was read", () => {
    expect(legibilityLabel("clear")).toBe("Read clearly");
    expect(legibilityLabel("partly")).toBe("Partly unclear");
    expect(legibilityLabel("poor")).toBe("Hard to read");
    expect(legibilityLabel(null)).toBeNull();
  });

  it("tells the learner what the worker is doing, and never shows a raw stage name", () => {
    expect(describeDocumentStage({ status: "running", stage: "extracting" })).toBe(
      "Reading the text…",
    );
    expect(describeDocumentStage({ status: "running", stage: "embedding" })).toBe(
      "Indexing the passages…",
    );
    expect(describeDocumentStage({ status: "queued", stage: "queued" })).toBe(
      "Waiting for a free worker…",
    );
    expect(describeDocumentStage({ status: "running", stage: "something_new" })).toBe(
      "Working on it…",
    );
  });
});

describe("documentPanelState", () => {
  it("shows live progress while the worker has the document", () => {
    const job = documentJob({ status: "running" });
    for (const status of ["queued", "processing"] as const) {
      expect(documentPanelState(studyDocument({ status, job }))).toEqual({ kind: "working", job });
    }
  });

  it("shows a document that waits for the learner, or is done", () => {
    expect(documentPanelState(studyDocument({ status: "review" }))).toEqual({ kind: "review" });
    expect(documentPanelState(studyDocument({ status: "ready" }))).toEqual({ kind: "ready" });
  });

  it("keeps showing progress when a reviewed document is being indexed", () => {
    const job = documentJob({ status: "queued", stage: "queued" });

    expect(documentPanelState(studyDocument({ status: "review", job }))).toEqual({
      kind: "working",
      job,
    });
  });

  it("reports a failure with the reason the API wrote", () => {
    const state = documentPanelState(
      studyDocument({ status: "failed", error_message: "This PDF is password-protected." }),
    );

    expect(state).toEqual({ kind: "failed", message: "This PDF is password-protected." });
  });

  it("does not wait for a job that has already ended", () => {
    const failed = documentJob({ status: "failed", error_message: "The AI service was busy." });
    const cancelled = documentJob({ status: "cancelled" });

    expect(documentPanelState(studyDocument({ status: "processing", job: failed }))).toEqual({
      kind: "failed",
      message: "The AI service was busy.",
    });
    expect(documentPanelState(studyDocument({ status: "queued", job: cancelled }))).toEqual({
      kind: "stopped",
    });
    expect(documentPanelState(studyDocument({ status: "queued", job: null }))).toEqual({
      kind: "stopped",
    });
  });
});

describe("anyWorking", () => {
  it("is true only while a job is active on a document that is not settled", () => {
    const active = documentJob({ status: "running" });
    expect(anyWorking([studyDocument({ status: "processing", job: active })])).toBe(true);
    expect(anyWorking([studyDocument({ status: "review", job: active })])).toBe(true);
    expect(anyWorking([studyDocument({ status: "ready" })])).toBe(false);
    expect(anyWorking([studyDocument({ status: "queued", job: null })])).toBe(false);
    expect(
      anyWorking([studyDocument({ status: "queued", job: documentJob({ status: "cancelled" }) })]),
    ).toBe(false);
    expect(anyWorking([])).toBe(false);
  });
});
