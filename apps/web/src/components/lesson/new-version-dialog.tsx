"use client";

import { RefreshCwIcon } from "lucide-react";

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
import { Textarea } from "@/components/ui/textarea";
import { generateLessonAction } from "@/lib/lessons/actions";
import { ADJUST_OPTIONS } from "@/lib/lessons/labels";

const MAX_FEEDBACK = 300;

type NewVersionDialogProps = {
  goalId: string;
  itemId: string;
};

/**
 * Ask for another version of this lesson: simpler, with more examples, or deeper, optionally with
 * a note. The new version is written from the existing lesson and the same topic; it never
 * replaces the current one while it is being made, and every earlier version stays available.
 */
export function NewVersionDialog({ goalId, itemId }: NewVersionDialogProps) {
  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button variant="outline">
          <RefreshCwIcon aria-hidden="true" />
          Write another version
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Write another version of this lesson</DialogTitle>
          <DialogDescription>
            It covers the same topic, starting from this lesson. The version you have now stays
            available while the new one is written.
          </DialogDescription>
        </DialogHeader>
        <form action={generateLessonAction.bind(null, goalId, itemId)} className="space-y-5">
          <input type="hidden" name="regenerate" value="1" />
          <fieldset className="space-y-2">
            <legend className="mb-1 text-sm font-medium">How should it differ?</legend>
            <label className="flex items-start gap-3 rounded-lg border p-3 text-sm has-checked:border-primary has-checked:bg-accent">
              <input type="radio" name="adjust" value="" defaultChecked className="mt-1" />
              <span>
                <span className="block font-medium">Just write it again</span>
                <span className="block text-muted-foreground">A fresh take on the same topic.</span>
              </span>
            </label>
            {ADJUST_OPTIONS.map((option) => (
              <label
                key={option.value}
                className="flex items-start gap-3 rounded-lg border p-3 text-sm has-checked:border-primary has-checked:bg-accent"
              >
                <input type="radio" name="adjust" value={option.value} className="mt-1" />
                <span>
                  <span className="block font-medium">{option.label}</span>
                  <span className="block text-muted-foreground">{option.hint}</span>
                </span>
              </label>
            ))}
          </fieldset>
          <FormField
            label="Anything else?"
            optional
            hint="For example: use cooking as the example, or skip the maths."
          >
            {(control) => (
              <Textarea
                {...control}
                name="feedback"
                maxLength={MAX_FEEDBACK}
                rows={3}
                placeholder="Optional"
              />
            )}
          </FormField>
          <DialogFooter>
            <DialogClose asChild>
              <Button type="button" variant="outline">
                Cancel
              </Button>
            </DialogClose>
            <SubmitButton>Write the new version</SubmitButton>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
