import Link from "next/link";

import { PageEditor } from "@/components/documents/page-editor";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { DocumentPages } from "@/lib/api/server";
import { legibilityLabel, pageLabel } from "@/lib/documents/labels";
import { documentPath } from "@/lib/documents/paths";

type PagesViewProps = {
  goalId: string;
  documentId: string;
  pages: DocumentPages;
  /** Real pages (a PDF or a picture) or parts of a text. */
  paginated: boolean;
};

/**
 * The text that was taken out of a document, page by page: what the passages (and so the lessons)
 * are built from. While the document waits for review, the pages that were read from a picture can
 * be corrected here.
 */
export function PagesView({ goalId, documentId, pages, paginated }: PagesViewProps) {
  const { items, total, offset, limit, editable } = pages;
  const end = offset + items.length;
  const base = documentPath(goalId, documentId);

  if (items.length === 0) {
    return <p className="text-sm text-muted-foreground">There is no extracted text to show yet.</p>;
  }

  return (
    <div className="space-y-4">
      <ol className="space-y-4">
        {items.map((page) => {
          const label = pageLabel(paginated, page.page_number);
          const reading = legibilityLabel(page.legibility);
          const canEdit = editable && page.source === "ocr";
          return (
            <li
              key={page.page_number}
              id={`page-${page.page_number}`}
              className="space-y-3 rounded-lg border bg-card p-4"
            >
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="font-heading text-base font-semibold">{label}</h3>
                {page.source === "ocr" ? (
                  <Badge variant="outline">Read from a picture</Badge>
                ) : null}
                {reading && page.source === "ocr" ? (
                  <Badge variant={page.legibility === "clear" ? "success" : "warning"}>
                    {reading}
                  </Badge>
                ) : null}
                {page.needs_review ? <Badge variant="warning">Check this page</Badge> : null}
                {page.edited ? <Badge variant="info">Corrected by you</Badge> : null}
              </div>
              {canEdit ? (
                <PageEditor
                  goalId={goalId}
                  documentId={documentId}
                  pageNumber={page.page_number}
                  label={label}
                  text={page.text}
                />
              ) : (
                <div className="max-h-96 overflow-y-auto text-sm leading-6 whitespace-pre-wrap">
                  {page.text || (
                    <span className="text-muted-foreground">No text on this page.</span>
                  )}
                </div>
              )}
            </li>
          );
        })}
      </ol>

      {total > limit ? (
        <nav aria-label="Pages of extracted text" className="flex items-center justify-between">
          <p className="text-sm text-muted-foreground">
            Showing {offset + 1}–{end} of {total}
          </p>
          <div className="flex gap-2">
            {offset > 0 ? (
              <Button asChild variant="outline" size="sm">
                <Link href={`${base}?offset=${Math.max(0, offset - limit)}`} scroll={false}>
                  Earlier
                </Link>
              </Button>
            ) : null}
            {end < total ? (
              <Button asChild variant="outline" size="sm">
                <Link href={`${base}?offset=${end}`} scroll={false}>
                  Later
                </Link>
              </Button>
            ) : null}
          </div>
        </nav>
      ) : null}
    </div>
  );
}
