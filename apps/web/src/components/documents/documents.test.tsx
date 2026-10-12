import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const nav = vi.hoisted(() => ({ refresh: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: nav.refresh }) }));

const actions = vi.hoisted(() => ({
  uploadDocumentAction: vi.fn(),
  pasteDocumentAction: vi.fn(),
  renameDocumentAction: vi.fn(),
  savePageAction: vi.fn(),
  confirmDocumentAction: vi.fn(),
  reprocessDocumentAction: vi.fn(),
  cancelDocumentJobAction: vi.fn(),
  deleteDocumentAction: vi.fn(),
  searchDocumentsAction: vi.fn(),
}));
vi.mock("@/lib/documents/actions", () => actions);

import { AutoRefresh } from "@/components/documents/auto-refresh";
import { DocumentActions, RenameForm } from "@/components/documents/document-actions";
import { DocumentCard } from "@/components/documents/document-card";
import { DocumentWorking } from "@/components/documents/document-working";
import { PagesView } from "@/components/documents/pages-view";
import { SearchPanel } from "@/components/documents/search-panel";
import { PasteForm, UploadForm } from "@/components/documents/upload-forms";
import { POLL_INTERVAL_MS } from "@/components/jobs/job-progress";
import {
  DOC,
  DOC_JOB,
  GOAL,
  documentJob,
  documentPage,
  documentPages,
  studyDocument,
} from "@/test-support/documents";

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("DocumentCard", () => {
  const card = (overrides = {}) =>
    render(
      <DocumentCard goalId={GOAL} document={studyDocument(overrides)} timeZone="Asia/Kolkata" />,
    );

  it("shows a ready document with what it is made of, and a way into it", () => {
    card();

    expect(screen.getByRole("link", { name: "Rust notes" })).toHaveAttribute(
      "href",
      `/goals/${GOAL}/documents/${DOC}`,
    );
    expect(screen.getByText("Ready")).toBeInTheDocument();
    expect(
      screen.getByText(/PDF · 20 KB · added 11 Oct 2026 · 3 pages · 7 passages/),
    ).toBeInTheDocument();
  });

  it("shows live progress in words while the worker has it", () => {
    card({
      status: "processing",
      job: documentJob({ status: "running", stage: "embedding", progress: 80 }),
    });

    expect(screen.getByText("Processing")).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Indexing the passages…" })).toBeInTheDocument();
  });

  it("says why it failed, using the reason the API wrote", () => {
    card({
      status: "failed",
      error_code: "PDF_ENCRYPTED",
      error_message: "This PDF is password-protected. Remove the password and upload it again.",
      job: documentJob({ status: "failed" }),
    });

    expect(screen.getByText("Couldn't process")).toBeInTheDocument();
    expect(screen.getByText(/password-protected/)).toBeInTheDocument();
  });

  it("asks the learner to check text that was read from a picture", () => {
    card({ status: "review", kind: "image", needs_review: true });

    expect(screen.getByText("Check the text")).toBeInTheDocument();
    expect(screen.getByText(/check it before it is used/i)).toBeInTheDocument();
  });

  it("does not claim progress for a job that was stopped", () => {
    card({ status: "queued", job: documentJob({ status: "cancelled" }) });

    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
    expect(screen.getByText(/processing was stopped/i)).toBeInTheDocument();
  });

  it("counts the notes about how it was read", () => {
    card({ warnings: [{ code: "PAGES_WITHOUT_TEXT", message: "Page 2 has no text.", page: 2 }] });

    expect(screen.getByText("1 note about how this was read.")).toBeInTheDocument();
  });

  it("shows a hostile title as text", () => {
    const { container } = card({ title: '<img src=x onerror="alert(1)">' });

    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText('<img src=x onerror="alert(1)">')).toBeInTheDocument();
  });
});

describe("UploadForm", () => {
  const MAX = 10 * 1024 * 1024;

  it("offers the file types that can be read, and says whether pictures are supported", () => {
    const { rerender } = render(<UploadForm goalId={GOAL} maxBytes={MAX} ocrAvailable />);
    const input = screen.getByLabelText("File");

    expect(input).toHaveAttribute("type", "file");
    expect(input.getAttribute("accept")).toContain(".pdf");
    expect(screen.getByText(/picture of printed or handwritten notes/i)).toBeInTheDocument();

    rerender(<UploadForm goalId={GOAL} maxBytes={MAX} ocrAvailable={false} />);
    expect(
      screen.getByText(/pictures and scanned pages can't be read on this server/i),
    ).toBeInTheDocument();
  });

  it("warns about a file over the limit before anything is sent", () => {
    render(<UploadForm goalId={GOAL} maxBytes={MAX} ocrAvailable />);
    const big = new File(["x"], "huge.pdf");
    Object.defineProperty(big, "size", { value: 12 * 1024 * 1024 });

    fireEvent.change(screen.getByLabelText("File"), { target: { files: [big] } });

    expect(screen.getByRole("alert")).toHaveTextContent(
      "That file is 12.0 MB. The limit is 10.0 MB.",
    );
    expect(screen.getByRole("button", { name: /upload/i })).toBeDisabled();
  });

  it("shows the server's reason next to the file input and keeps the title", async () => {
    actions.uploadDocumentAction.mockResolvedValue({
      status: "error",
      fieldErrors: { file: "This kind of file can't be used." },
      values: { title: "My notes" },
    });
    render(<UploadForm goalId={GOAL} maxBytes={MAX} ocrAvailable />);
    await userEvent.type(screen.getByLabelText(/Title/), "My notes");

    await userEvent.upload(screen.getByLabelText("File"), new File(["x"], "a.txt"));
    await userEvent.click(screen.getByRole("button", { name: /upload/i }));

    expect(await screen.findByText("This kind of file can't be used.")).toBeInTheDocument();
    expect(screen.getByLabelText("File")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByLabelText(/Title/)).toHaveValue("My notes");
  });
});

describe("PasteForm", () => {
  it("shows what is wrong and keeps what was typed", async () => {
    actions.pasteDocumentAction.mockResolvedValue({
      status: "error",
      fieldErrors: { title: "Give this material a title." },
      values: { title: "", text: "Ownership is..." },
    });
    render(<PasteForm goalId={GOAL} />);

    await userEvent.type(screen.getByLabelText("Text"), "Ownership is...");
    await userEvent.click(screen.getByRole("button", { name: /add pasted text/i }));

    expect(await screen.findByText("Give this material a title.")).toBeInTheDocument();
    expect(screen.getByLabelText("Text")).toHaveValue("Ownership is...");
  });
});

describe("PagesView", () => {
  it("shows the extracted text of each page", () => {
    render(
      <PagesView
        goalId={GOAL}
        documentId={DOC}
        paginated
        pages={documentPages([
          documentPage({ page_number: 1, text: "First page text" }),
          documentPage({ page_number: 2, text: "Second page text" }),
        ])}
      />,
    );

    expect(screen.getByRole("heading", { name: "Page 1" })).toBeInTheDocument();
    expect(screen.getByText("First page text")).toBeInTheDocument();
    expect(screen.getByText("Second page text")).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("calls parts of a text parts, not pages", () => {
    render(<PagesView goalId={GOAL} documentId={DOC} paginated={false} pages={documentPages()} />);

    expect(screen.getByRole("heading", { name: "Part 1" })).toBeInTheDocument();
  });

  it("lets the learner correct text read from a picture while it waits for review", () => {
    render(
      <PagesView
        goalId={GOAL}
        documentId={DOC}
        paginated
        pages={documentPages(
          [
            documentPage({
              page_number: 1,
              source: "ocr",
              legibility: "partly",
              needs_review: true,
              text: "Ownershp meens wun ownr",
            }),
            documentPage({ page_number: 2, text: "A printed page" }),
          ],
          { editable: true },
        )}
      />,
    );

    expect(screen.getByLabelText("Text of page 1")).toHaveValue("Ownershp meens wun ownr");
    expect(screen.getByText("Read from a picture")).toBeInTheDocument();
    expect(screen.getByText("Partly unclear")).toBeInTheDocument();
    expect(screen.getByText("Check this page")).toBeInTheDocument();
    // A page that came from the file's own text is not offered for editing.
    expect(screen.queryByLabelText("Text of page 2")).not.toBeInTheDocument();
  });

  it("marks a page the learner has corrected", () => {
    render(
      <PagesView
        goalId={GOAL}
        documentId={DOC}
        paginated
        pages={documentPages([documentPage({ source: "ocr", legibility: "clear", edited: true })])}
      />,
    );

    expect(screen.getByText("Corrected by you")).toBeInTheDocument();
  });

  it("pages through a long document with links that name an offset", () => {
    render(
      <PagesView
        goalId={GOAL}
        documentId={DOC}
        paginated
        pages={{
          items: [documentPage({ page_number: 21 })],
          total: 45,
          offset: 20,
          limit: 20,
          editable: false,
        }}
      />,
    );

    expect(screen.getByText("Showing 21–21 of 45")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Earlier" })).toHaveAttribute(
      "href",
      `/goals/${GOAL}/documents/${DOC}?offset=0`,
    );
    expect(screen.getByRole("link", { name: "Later" })).toHaveAttribute(
      "href",
      `/goals/${GOAL}/documents/${DOC}?offset=21`,
    );
  });

  it("renders extracted text as text, never as markup", () => {
    const hostile = '<script>alert(1)</script><img src=x onerror="alert(1)">';
    const { container } = render(
      <PagesView
        goalId={GOAL}
        documentId={DOC}
        paginated
        pages={documentPages([documentPage({ text: hostile })])}
      />,
    );

    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText(hostile)).toBeInTheDocument();
  });
});

describe("SearchPanel", () => {
  const hit = {
    chunk_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    document_id: DOC,
    document_title: "Rust notes",
    page_start: 3,
    page_end: 3,
    position: "p. 3",
    section_title: null,
    content: "Each value has exactly one owner.",
    similarity: 0.82,
    keyword_match: true,
  };

  async function ask(result: unknown) {
    actions.searchDocumentsAction.mockResolvedValue({
      status: "results",
      query: "ownership",
      result,
    });
    render(<SearchPanel goalId={GOAL} />);
    await userEvent.type(screen.getByLabelText("Question or keywords"), "ownership");
    await userEvent.click(screen.getByRole("button", { name: /search/i }));
  }

  it("shows the passages that were found, with the document and the page", async () => {
    await ask({ items: [hit], enough_evidence: true, searched_documents: 2 });

    expect(await screen.findByText("1 passage found in 2 documents.")).toBeInTheDocument();
    const item = screen.getByRole("listitem");
    expect(within(item).getByRole("link", { name: "Rust notes" })).toHaveAttribute(
      "href",
      `/goals/${GOAL}/documents/${DOC}`,
    );
    expect(within(item).getByText("p. 3")).toBeInTheDocument();
    expect(within(item).getByText("Each value has exactly one owner.")).toBeInTheDocument();
  });

  it("says so when nothing in the material covers the question", async () => {
    await ask({ items: [], enough_evidence: false, searched_documents: 1 });

    expect(await screen.findByText(/nothing in your documents covers that/i)).toBeInTheDocument();
    expect(screen.queryByRole("listitem")).not.toBeInTheDocument();
  });

  it("says there is nothing to search when no document is ready", async () => {
    await ask({ items: [], enough_evidence: false, searched_documents: 0 });

    expect(await screen.findByText(/no processed documents to search yet/i)).toBeInTheDocument();
  });

  it("shows a failed search next to the field", async () => {
    actions.searchDocumentsAction.mockResolvedValue({
      status: "error",
      message: "Search isn't available right now. Please try again in a moment.",
      query: "ownership",
    });
    render(<SearchPanel goalId={GOAL} />);

    await userEvent.type(screen.getByLabelText("Question or keywords"), "ownership");
    await userEvent.click(screen.getByRole("button", { name: /search/i }));

    expect(await screen.findByText(/search isn't available right now/i)).toBeInTheDocument();
  });
});

describe("DocumentWorking and AutoRefresh", () => {
  it("shows the stage in words and lets the learner stop the job", () => {
    render(
      <DocumentWorking
        goalId={GOAL}
        documentId={DOC}
        job={documentJob({ status: "running", stage: "reading_pages", progress: 45 })}
      />,
    );

    expect(screen.getByText("Reading your document")).toBeInTheDocument();
    expect(
      screen.getByRole("progressbar", { name: "Reading the scanned pages…" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
  });

  it("binds the cancel action to this goal, document and job", async () => {
    render(
      <DocumentWorking
        goalId={GOAL}
        documentId={DOC}
        job={documentJob({ id: DOC_JOB, status: "running" })}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));

    await waitFor(() =>
      expect(actions.cancelDocumentJobAction).toHaveBeenCalledWith(
        GOAL,
        DOC,
        DOC_JOB,
        expect.anything(),
      ),
    );
  });

  it("asks the server for fresh state on a timer, and stops when it goes away", () => {
    vi.useFakeTimers();
    const { unmount } = render(<AutoRefresh />);

    act(() => {
      vi.advanceTimersByTime(POLL_INTERVAL_MS * 3);
    });
    expect(nav.refresh).toHaveBeenCalledTimes(3);

    unmount();
    act(() => {
      vi.advanceTimersByTime(POLL_INTERVAL_MS * 3);
    });
    expect(nav.refresh).toHaveBeenCalledTimes(3);
  });
});

describe("DocumentActions and RenameForm", () => {
  it("downloads the original as an attachment through the app, not a storage link", () => {
    render(<DocumentActions goalId={GOAL} documentId={DOC} busy={false} readOnly={false} />);

    const link = screen.getByRole("link", { name: /download original/i });
    expect(link).toHaveAttribute("href", `/goals/${GOAL}/documents/${DOC}/file`);
    expect(link).toHaveAttribute("download");
  });

  it("asks before processing again or deleting", async () => {
    render(<DocumentActions goalId={GOAL} documentId={DOC} busy={false} readOnly={false} />);

    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/removed for good/i)).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Delete forever" })).toBeInTheDocument();
    expect(actions.deleteDocumentAction).not.toHaveBeenCalled();
  });

  it("offers neither while the document is being processed or the goal is archived", () => {
    const { rerender } = render(
      <DocumentActions goalId={GOAL} documentId={DOC} busy readOnly={false} />,
    );
    expect(screen.queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Process again" })).not.toBeInTheDocument();

    rerender(<DocumentActions goalId={GOAL} documentId={DOC} busy={false} readOnly />);
    expect(screen.queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /download original/i })).toBeInTheDocument();
  });

  it("renames in place and confirms it", async () => {
    actions.renameDocumentAction.mockResolvedValue({
      status: "success",
      message: "Title saved.",
      values: { title: "Chapter 4" },
    });
    render(<RenameForm goalId={GOAL} documentId={DOC} title="Rust notes" />);

    const input = screen.getByLabelText("Title");
    await userEvent.clear(input);
    await userEvent.type(input, "Chapter 4");
    await userEvent.click(screen.getByRole("button", { name: "Rename" }));

    expect(await screen.findByText("Title saved.")).toBeInTheDocument();
    expect(screen.getByLabelText("Title")).toHaveValue("Chapter 4");
  });
});
