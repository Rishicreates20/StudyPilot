"use client";

import { DownloadIcon, PencilIcon, RotateCcwIcon, Trash2Icon } from "lucide-react";
import { useActionState } from "react";

import { FormAlert } from "@/components/forms/form-alert";
import { FormField } from "@/components/forms/form-field";
import { SubmitButton } from "@/components/forms/submit-button";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  deleteDocumentAction,
  reprocessDocumentAction,
  renameDocumentAction,
} from "@/lib/documents/actions";
import { documentFilePath } from "@/lib/documents/paths";
import type { RenameFormState } from "@/lib/documents/schema";

const IDLE = { status: "idle" } as const;

/** Rename the document in place. */
export function RenameForm({
  goalId,
  documentId,
  title,
}: {
  goalId: string;
  documentId: string;
  title: string;
}) {
  const [state, action] = useActionState<RenameFormState, FormData>(
    renameDocumentAction.bind(null, goalId, documentId),
    IDLE,
  );
  const shown = state.status === "idle" ? title : (state.values?.title ?? title);

  return (
    <form action={action} className="space-y-3" noValidate>
      {state.status === "error" && state.formError ? <FormAlert message={state.formError} /> : null}
      <FormField
        label="Title"
        error={state.status === "error" ? state.fieldErrors.title : undefined}
      >
        {(control) => (
          <div className="flex gap-2">
            <Input
              {...control}
              name="title"
              key={shown}
              defaultValue={shown}
              maxLength={200}
              autoComplete="off"
              required
            />
            <SubmitButton variant="outline">
              <PencilIcon aria-hidden="true" />
              Rename
            </SubmitButton>
          </div>
        )}
      </FormField>
      {state.status === "success" ? (
        <p role="status" className="text-sm text-success-foreground">
          {state.message}
        </p>
      ) : null}
    </form>
  );
}

/** Download the original, read the file again from scratch, or delete everything about it. */
export function DocumentActions({
  goalId,
  documentId,
  busy,
  readOnly,
}: {
  goalId: string;
  documentId: string;
  /** The document is being processed: it can't be processed again or deleted right now. */
  busy: boolean;
  /** The goal is archived: documents are read-only. */
  readOnly: boolean;
}) {
  return (
    <div className="flex flex-wrap gap-2">
      <Button asChild variant="outline">
        {/* A plain link: the route streams the file as an attachment (never shown inline). */}
        <a href={documentFilePath(goalId, documentId)} download>
          <DownloadIcon aria-hidden="true" />
          Download original
        </a>
      </Button>

      {!busy && !readOnly ? (
        <Dialog>
          <DialogTrigger asChild>
            <Button variant="outline">
              <RotateCcwIcon aria-hidden="true" />
              Process again
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Process this document again?</DialogTitle>
              <DialogDescription>
                The file is read from the start. Any corrections you made to its text are discarded.
              </DialogDescription>
            </DialogHeader>
            <form action={reprocessDocumentAction.bind(null, goalId, documentId)}>
              <DialogFooter>
                <DialogClose asChild>
                  <Button type="button" variant="outline">
                    Cancel
                  </Button>
                </DialogClose>
                <SubmitButton>Process again</SubmitButton>
              </DialogFooter>
            </form>
          </DialogContent>
        </Dialog>
      ) : null}

      {!busy && !readOnly ? (
        <Dialog>
          <DialogTrigger asChild>
            <Button variant="destructive">
              <Trash2Icon aria-hidden="true" />
              Delete
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Delete this document?</DialogTitle>
              <DialogDescription>
                The file, the text taken from it and its indexed passages are removed for good.
                Lessons already written keep their wording, but their citations of this document
                will show as unavailable.
              </DialogDescription>
            </DialogHeader>
            <form action={deleteDocumentAction.bind(null, goalId, documentId)}>
              <DialogFooter>
                <DialogClose asChild>
                  <Button type="button" variant="outline">
                    Cancel
                  </Button>
                </DialogClose>
                <SubmitButton variant="destructive">Delete forever</SubmitButton>
              </DialogFooter>
            </form>
          </DialogContent>
        </Dialog>
      ) : null}
    </div>
  );
}
