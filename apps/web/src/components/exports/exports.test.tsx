import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const actions = vi.hoisted(() => ({
  requestLessonExportAction: vi.fn(),
  requestRoadmapExportAction: vi.fn(),
  deleteExportAction: vi.fn(),
}));
vi.mock("@/lib/exports/actions", () => actions);

import { ExportCard } from "@/components/exports/export-card";
import { ExportPanel } from "@/components/exports/export-panel";
import { EXPORT, GOAL, LESSON, ROADMAP, exportItem, exportJob } from "@/test-support/exports";

beforeEach(() => {
  vi.clearAllMocks();
});

describe("ExportCard", () => {
  const card = (overrides = {}, readOnly = false) =>
    render(
      <ExportCard
        goalId={GOAL}
        item={exportItem(overrides)}
        timeZone="Asia/Kolkata"
        readOnly={readOnly}
      />,
    );

  it("shows a ready file with what it was made from, and a plain download link through the app", () => {
    card();

    expect(screen.getByRole("heading", { name: "Study notes (PDF)" })).toBeInTheDocument();
    expect(screen.getByText('Lesson "Ownership in Rust", version 2')).toBeInTheDocument();
    expect(screen.getByText("20 KB · 3 pages · made 11 Oct 2026")).toBeInTheDocument();
    expect(screen.getByText("Ready to download")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Download Study notes (PDF): Ownership in Rust" }),
    ).toHaveAttribute("href", `/goals/${GOAL}/exports/${EXPORT}/download`);
    expect(screen.queryByRole("button", { name: /try again/i })).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Delete Study notes (PDF): Ownership in Rust" }),
    ).toBeInTheDocument();
  });

  it("names a roadmap's slides as a roadmap deck counted in slides", () => {
    card({
      lesson_id: null,
      roadmap_id: ROADMAP,
      source_title: "Rust in six weeks",
      source_version: 1,
      format: "slides_pptx",
      page_count: 14,
    });

    expect(screen.getByRole("heading", { name: "Slides (PowerPoint)" })).toBeInTheDocument();
    expect(screen.getByText('Roadmap "Rust in six weeks", version 1')).toBeInTheDocument();
    expect(screen.getByText(/14 slides/)).toBeInTheDocument();
  });

  it("shows live progress in words while the file is being made, and offers no download or delete", () => {
    card({
      status: "processing",
      ready_at: null,
      size_bytes: null,
      page_count: null,
      job: exportJob({ status: "running", stage: "rendering", progress: 35 }),
    });

    expect(screen.getByText("Being made")).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Laying out the file" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /download/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /delete/i })).not.toBeInTheDocument();
  });

  it("says why a file couldn't be made and offers to try the same format again", () => {
    card({
      status: "failed",
      ready_at: null,
      job: exportJob({
        status: "failed",
        error_code: "EXPORT_LINK_EXPIRED",
        error_message: "The link for storing this file has expired. Ask for the export again.",
      }),
    });

    expect(screen.getByText("Couldn't be made")).toBeInTheDocument();
    expect(
      screen.getByText("The link for storing this file has expired. Ask for the export again."),
    ).toBeInTheDocument();
    const retry = screen.getByRole("button", { name: "Try again" });
    const retryForm = retry.closest("form");
    expect(retryForm).not.toBeNull();
    expect(within(retryForm as HTMLFormElement).getByDisplayValue("notes_pdf")).toHaveAttribute(
      "name",
      "format",
    );
    expect(screen.queryByRole("link", { name: /download/i })).not.toBeInTheDocument();
  });

  it("does not offer to try again on an archived goal, but still allows deleting", () => {
    card({ status: "failed", ready_at: null }, true);

    expect(screen.queryByRole("button", { name: "Try again" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /delete/i })).toBeInTheDocument();
  });

  it("warns, in words, when characters had to be replaced", () => {
    const { unmount } = card({ unsupported_characters: 1 });
    expect(
      screen.getByText(
        "1 character couldn't be shown in this file's fonts and was replaced with a placeholder mark.",
      ),
    ).toBeInTheDocument();
    unmount();

    card({ unsupported_characters: 4 });
    expect(
      screen.getByText(
        "4 characters couldn't be shown in this file's fonts and were replaced with a placeholder mark.",
      ),
    ).toBeInTheDocument();
  });

  it("does not warn when every character could be shown", () => {
    card({ unsupported_characters: 0 });

    expect(screen.queryByText(/placeholder mark/)).not.toBeInTheDocument();
  });
});

describe("ExportPanel", () => {
  const formatButtons = () =>
    screen
      .getAllByRole("button")
      .map((button) => [button.getAttribute("name"), button.getAttribute("value")]);

  it("offers a lesson's three formats as buttons of one form, the clicked one being the format", () => {
    render(<ExportPanel goalId={GOAL} kind="lesson" sourceId={LESSON} returnTo="/here" />);

    expect(screen.getByRole("heading", { level: 2, name: "Download a copy" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Download a copy" })).toBeInTheDocument();
    expect(formatButtons()).toEqual([
      ["format", "notes_pdf"],
      ["format", "revision_pdf"],
      ["format", "slides_pptx"],
    ]);
    expect(screen.getByRole("button", { name: /Study notes \(PDF\)/ })).toHaveAttribute(
      "type",
      "submit",
    );
    expect(screen.getByRole("link", { name: "Your exported files" })).toHaveAttribute(
      "href",
      `/goals/${GOAL}/exports`,
    );
  });

  it("offers a roadmap PDF and slides for a roadmap", () => {
    render(<ExportPanel goalId={GOAL} kind="roadmap" sourceId={ROADMAP} returnTo="/here" />);

    expect(formatButtons()).toEqual([
      ["format", "roadmap_pdf"],
      ["format", "slides_pptx"],
    ]);
  });

  it("explains that an archived goal makes no new files, and still links to the earlier ones", () => {
    render(<ExportPanel goalId={GOAL} kind="lesson" sourceId={LESSON} returnTo="/here" readOnly />);

    expect(screen.queryAllByRole("button")).toHaveLength(0);
    expect(screen.getByText(/This goal is archived/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Your exported files" })).toBeInTheDocument();
  });
});
