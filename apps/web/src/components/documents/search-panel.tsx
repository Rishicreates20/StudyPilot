"use client";

import { SearchIcon } from "lucide-react";
import Link from "next/link";
import { useActionState } from "react";

import { FormField } from "@/components/forms/form-field";
import { SubmitButton } from "@/components/forms/submit-button";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { searchDocumentsAction } from "@/lib/documents/actions";
import { documentPath } from "@/lib/documents/paths";
import type { SearchState } from "@/lib/documents/schema";

const IDLE: SearchState = { status: "idle" };

/**
 * Ask your documents a question. Only the passages that were really found are shown, each with the
 * document and page it came from; when nothing in the material covers the question it says so
 * rather than guessing.
 */
export function SearchPanel({ goalId }: { goalId: string }) {
  const [state, action] = useActionState<SearchState, FormData>(
    searchDocumentsAction.bind(null, goalId),
    IDLE,
  );
  const query = state.status === "idle" ? "" : state.query;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-lg">
          <SearchIcon className="size-5 text-primary" aria-hidden="true" />
          <h2>Search your material</h2>
        </CardTitle>
        <CardDescription>
          Find the passages that answer a question. Lessons for this goal draw on the same passages.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <form action={action} className="space-y-3" noValidate role="search">
          <FormField
            label="Question or keywords"
            error={state.status === "error" ? state.message : undefined}
          >
            {(control) => (
              <Input
                {...control}
                name="query"
                type="search"
                maxLength={500}
                defaultValue={query}
                placeholder="What does ownership mean?"
                autoComplete="off"
                required
              />
            )}
          </FormField>
          <SubmitButton>
            <SearchIcon aria-hidden="true" />
            Search
          </SubmitButton>
        </form>

        {state.status === "results" ? (
          <div aria-live="polite" className="space-y-3">
            {state.result.enough_evidence ? (
              <>
                <p className="text-sm text-muted-foreground">
                  {state.result.items.length === 1
                    ? "1 passage found"
                    : `${state.result.items.length} passages found`}{" "}
                  in{" "}
                  {state.result.searched_documents === 1
                    ? "1 document"
                    : `${state.result.searched_documents} documents`}
                  .
                </p>
                <ol className="space-y-3">
                  {state.result.items.map((hit) => (
                    <li key={hit.chunk_id} className="space-y-2 rounded-lg border bg-card p-4">
                      <div className="flex flex-wrap items-center gap-2 text-sm">
                        <Link
                          href={documentPath(goalId, hit.document_id)}
                          className="rounded-sm font-medium underline-offset-4 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                        >
                          {hit.document_title}
                        </Link>
                        <Badge variant="outline">{hit.position}</Badge>
                        {hit.section_title ? (
                          <span className="text-muted-foreground">{hit.section_title}</span>
                        ) : null}
                      </div>
                      <p className="text-sm leading-6 whitespace-pre-line">{hit.content}</p>
                    </li>
                  ))}
                </ol>
              </>
            ) : (
              <Alert variant="info">
                <AlertDescription>
                  {state.result.searched_documents === 0
                    ? "There are no processed documents to search yet. Add one above and wait for it to be ready."
                    : "Nothing in your documents covers that. Try different words, or add material that does."}
                </AlertDescription>
              </Alert>
            )}
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
