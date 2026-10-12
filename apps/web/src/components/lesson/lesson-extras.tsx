import { BookOpenCheckIcon, CircleXIcon, FileTextIcon, InfoIcon } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { Inline } from "@/components/lesson/lesson-blocks";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { Citation, LessonDocument } from "@/lib/api/server";
import { documentPath } from "@/lib/documents/paths";

function ExtraSection({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section aria-labelledby={id} className="space-y-4">
      <h2 id={id} className="font-heading text-xl font-semibold tracking-tight">
        {title}
      </h2>
      {children}
    </section>
  );
}

/** The key terms of the topic, each defined once. */
export function KeyTerms({ definitions }: { definitions: LessonDocument["definitions"] }) {
  if (definitions.length === 0) return null;
  return (
    <ExtraSection id="key-terms" title="Key terms">
      <dl className="grid gap-3 sm:grid-cols-2">
        {definitions.map((definition) => (
          <div key={definition.term} className="rounded-lg border bg-card p-4">
            <dt className="font-medium">{definition.term}</dt>
            <dd className="mt-1 text-sm leading-6 text-muted-foreground">
              <Inline text={definition.meaning} />
            </dd>
          </div>
        ))}
      </dl>
    </ExtraSection>
  );
}

/** Complete examples, worked through step by step. */
export function WorkedExamples({ examples }: { examples: LessonDocument["worked_examples"] }) {
  if (examples.length === 0) return null;
  return (
    <ExtraSection id="worked-examples" title="Worked examples">
      <div className="space-y-4">
        {examples.map((example) => (
          <Card key={example.title}>
            <CardHeader>
              <CardTitle className="text-base">
                <h3>{example.title}</h3>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4 text-sm leading-6">
              <p>
                <span className="font-medium">Problem: </span>
                <Inline text={example.problem} />
              </p>
              <ol className="list-decimal space-y-1.5 pl-6">
                {example.steps.map((step, index) => (
                  <li key={index} className="pl-1">
                    <Inline text={step} />
                  </li>
                ))}
              </ol>
              <p className="rounded-md bg-muted px-3 py-2">
                <span className="font-medium">Result: </span>
                <Inline text={example.answer} />
              </p>
            </CardContent>
          </Card>
        ))}
      </div>
    </ExtraSection>
  );
}

/** Mistakes learners often make with this topic, next to what is true. */
export function Misconceptions({ items }: { items: LessonDocument["common_misconceptions"] }) {
  if (items.length === 0) return null;
  return (
    <ExtraSection id="misconceptions" title="Common mistakes">
      <ul className="space-y-3">
        {items.map((item) => (
          <li key={item.misconception} className="space-y-2 rounded-lg border bg-card p-4 text-sm">
            <p className="flex gap-2 leading-6">
              <CircleXIcon className="mt-1 size-4 shrink-0 text-destructive" aria-hidden="true" />
              <span>
                <span className="font-medium">Often believed: </span>
                <Inline text={item.misconception} />
              </span>
            </p>
            <p className="flex gap-2 leading-6">
              <BookOpenCheckIcon className="mt-1 size-4 shrink-0 text-success" aria-hidden="true" />
              <span>
                <span className="font-medium">Actually: </span>
                <Inline text={item.correction} />
              </span>
            </p>
          </li>
        ))}
      </ul>
    </ExtraSection>
  );
}

export function SummaryList({ summary }: { summary: string[] }) {
  return (
    <ExtraSection id="summary" title="Summary">
      <ul className="list-disc space-y-2 pl-6 leading-7">
        {summary.map((point, index) => (
          <li key={index} className="pl-1">
            <Inline text={point} />
          </li>
        ))}
      </ul>
    </ExtraSection>
  );
}

/**
 * Where the lesson's explanation comes from.
 *
 * - A lesson that cites the learner's own documents lists each passage it used: the document, where
 *   in it, the lesson's note, and the passage itself, looked up as it is now (a document deleted
 *   since shows as unavailable, with no copy of its text).
 * - A lesson written while the learner had documents, but none that covered the topic, says so
 *   plainly rather than pretending to rest on them.
 * - Any other lesson says it is written from general knowledge, so it is never taken for
 *   something checked against a document.
 */
export function Sources({
  goalId,
  grounding,
  references,
  citations = [],
}: {
  goalId: string;
  grounding: LessonDocument["grounding"];
  references: LessonDocument["source_references"];
  citations?: readonly Citation[];
}) {
  if (references.length === 0 || grounding !== "sources") {
    return (
      <p className="flex items-start gap-2 text-sm text-muted-foreground">
        <InfoIcon className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
        {grounding === "no_match"
          ? "You have study material for this goal, but nothing in it covered this topic closely enough, so this lesson is written from general knowledge, not from your documents. Check anything important against a source you trust."
          : "This lesson is written from general knowledge, not from your own material, and has no sources to cite. Check anything important against a source you trust."}
      </p>
    );
  }
  return (
    <ExtraSection id="sources" title="Sources">
      <p className="text-sm text-muted-foreground">
        This lesson draws on these passages from your own documents.
      </p>
      <ol className="space-y-3 text-sm">
        {references.map((reference) => {
          const citation = citations.find((candidate) => candidate.chunk_id === reference.chunk_id);
          return (
            <li
              key={`${reference.source_id}:${reference.chunk_id}`}
              className="space-y-2 rounded-lg border bg-card p-3"
            >
              <div className="flex flex-wrap items-center gap-2">
                <FileTextIcon className="size-4 shrink-0 text-primary" aria-hidden="true" />
                {citation?.available && citation.document_id ? (
                  <Link
                    href={documentPath(goalId, citation.document_id)}
                    className="rounded-sm font-medium underline-offset-4 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                  >
                    {citation.document_title}
                  </Link>
                ) : (
                  <span className="font-medium">A document you have since deleted</span>
                )}
                {citation?.position ? <Badge variant="outline">{citation.position}</Badge> : null}
              </div>
              {reference.note ? <p className="text-muted-foreground">{reference.note}</p> : null}
              {citation?.excerpt ? (
                <blockquote className="border-l-2 border-primary/40 pl-3 leading-6 text-muted-foreground">
                  {citation.excerpt}
                </blockquote>
              ) : null}
            </li>
          );
        })}
      </ol>
    </ExtraSection>
  );
}

/** The same topic in everyday words, with a familiar comparison. */
export function SimpleExplanationCard({
  explanation,
}: {
  explanation: LessonDocument["simple_explanation"];
}) {
  return (
    <section
      aria-labelledby="simple-explanation"
      className="space-y-3 rounded-xl border border-info/30 bg-info-soft p-5 text-info-foreground"
    >
      <h2 id="simple-explanation" className="font-heading text-lg font-semibold">
        In simple words
      </h2>
      <div className="space-y-3 leading-7">
        {explanation.paragraphs.map((paragraph, index) => (
          <p key={index}>
            <Inline text={paragraph} />
          </p>
        ))}
      </div>
      {explanation.analogy ? (
        <p className="rounded-lg bg-background/60 px-3 py-2 text-sm leading-6">
          <span className="font-medium">Think of it like this: </span>
          <Inline text={explanation.analogy} />
        </p>
      ) : null}
    </section>
  );
}
