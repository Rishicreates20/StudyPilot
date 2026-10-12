"use client";

import { ClipboardPasteIcon, UploadIcon } from "lucide-react";
import { useActionState, useState } from "react";

import { FormAlert } from "@/components/forms/form-alert";
import { FormField } from "@/components/forms/form-field";
import { SubmitButton } from "@/components/forms/submit-button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { pasteDocumentAction, uploadDocumentAction } from "@/lib/documents/actions";
import { formatBytes } from "@/lib/documents/labels";
import type { PasteFormState, UploadFormState } from "@/lib/documents/schema";

const IDLE = { status: "idle" } as const;
/** What the file chooser offers. The API decides what a file really is from its content. */
const ACCEPT = ".pdf,.txt,.md,.markdown,.png,.jpg,.jpeg,.webp,application/pdf,text/plain,image/*";

type UploadFormProps = {
  goalId: string;
  maxBytes: number;
  /** Whether scanned pages and pictures can be read on this server. */
  ocrAvailable: boolean;
};

/** Choose a PDF, a text file or a picture of notes. The file is checked again by the server. */
export function UploadForm({ goalId, maxBytes, ocrAvailable }: UploadFormProps) {
  const [state, action] = useActionState<UploadFormState, FormData>(
    uploadDocumentAction.bind(null, goalId),
    IDLE,
  );
  const [tooBig, setTooBig] = useState<string | null>(null);
  const values = state.status === "error" ? state.values : { title: "" };
  const errors = state.status === "error" ? state.fieldErrors : {};

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-lg">
          <UploadIcon className="size-5 text-primary" aria-hidden="true" />
          <h2>Upload a file</h2>
        </CardTitle>
        <CardDescription>
          A PDF, a text file (.txt, .md)
          {ocrAvailable ? " or a picture of printed or handwritten notes" : ""}. Up to{" "}
          {formatBytes(maxBytes)}. Your files stay private to your account.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form action={action} className="space-y-4" noValidate>
          {state.status === "error" && state.formError ? (
            <FormAlert message={state.formError} />
          ) : null}
          <FormField
            label="File"
            error={tooBig ?? errors.file}
            hint={
              ocrAvailable
                ? "Scanned pages and pictures are read by an AI model; you can check what it read before it is used."
                : "Pictures and scanned pages can't be read on this server."
            }
          >
            {(control) => (
              <Input
                {...control}
                type="file"
                name="file"
                accept={ACCEPT}
                required
                onChange={(event) => {
                  const file = event.currentTarget.files?.[0];
                  setTooBig(
                    file && file.size > maxBytes
                      ? `That file is ${formatBytes(file.size)}. The limit is ${formatBytes(maxBytes)}.`
                      : null,
                  );
                }}
              />
            )}
          </FormField>
          <FormField
            label="Title"
            optional
            error={errors.title}
            hint="Defaults to the file's name."
          >
            {(control) => (
              <Input
                {...control}
                name="title"
                maxLength={200}
                defaultValue={values.title ?? ""}
                autoComplete="off"
              />
            )}
          </FormField>
          <SubmitButton disabled={tooBig !== null}>
            <UploadIcon aria-hidden="true" />
            Upload
          </SubmitButton>
        </form>
      </CardContent>
    </Card>
  );
}

/** Paste text straight from a textbook, a slide or your own notes. */
export function PasteForm({ goalId }: { goalId: string }) {
  const [state, action] = useActionState<PasteFormState, FormData>(
    pasteDocumentAction.bind(null, goalId),
    IDLE,
  );
  const values = state.status === "error" ? state.values : { title: "", text: "" };
  const errors = state.status === "error" ? state.fieldErrors : {};

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-lg">
          <ClipboardPasteIcon className="size-5 text-primary" aria-hidden="true" />
          <h2>Paste text</h2>
        </CardTitle>
        <CardDescription>
          Use this for a chapter, a set of notes or anything you can copy.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form action={action} className="space-y-4" noValidate>
          {state.status === "error" && state.formError ? (
            <FormAlert message={state.formError} />
          ) : null}
          <FormField label="Title" error={errors.title}>
            {(control) => (
              <Input
                {...control}
                name="title"
                maxLength={200}
                defaultValue={values.title ?? ""}
                autoComplete="off"
                required
              />
            )}
          </FormField>
          <FormField label="Text" error={errors.text}>
            {(control) => (
              <Textarea
                {...control}
                name="text"
                rows={8}
                defaultValue={values.text ?? ""}
                required
              />
            )}
          </FormField>
          <SubmitButton>
            <ClipboardPasteIcon aria-hidden="true" />
            Add pasted text
          </SubmitButton>
        </form>
      </CardContent>
    </Card>
  );
}
