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
import { generateRoadmapAction } from "@/lib/roadmaps/actions";

const MAX_FEEDBACK = 500;

type RegenerateDialogProps = {
  goalId: string;
  /** "Revise" when there is a plan to change, "Generate" when this is the first one. */
  hasRoadmap: boolean;
};

/**
 * Ask for a new version of the roadmap, optionally saying what should change. It never replaces
 * or edits the existing plan: the result is added as the next version, and every earlier version
 * stays available.
 */
export function RegenerateDialog({ goalId, hasRoadmap }: RegenerateDialogProps) {
  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button variant="outline">
          <RefreshCwIcon aria-hidden="true" />
          {hasRoadmap ? "Revise or regenerate" : "Generate roadmap"}
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{hasRoadmap ? "Make a new version" : "Generate a roadmap"}</DialogTitle>
          <DialogDescription>
            {hasRoadmap
              ? "A new version is added, planned from this goal and from the documents on it that are ready now. Your current roadmap and every earlier version stay available, and you can switch back at any time."
              : "Your roadmap is planned from this goal's level, daily time and target date, and from the documents on it that are ready."}
          </DialogDescription>
        </DialogHeader>
        <form action={generateRoadmapAction.bind(null, goalId)} className="space-y-5">
          <FormField
            label="What should change?"
            optional
            hint={
              hasRoadmap
                ? "For example: fewer topics, more practice problems, or skip the basics. Leave it empty for a fresh plan."
                : "Anything the plan should focus on or avoid."
            }
          >
            {(control) => (
              <Textarea
                {...control}
                name="feedback"
                maxLength={MAX_FEEDBACK}
                rows={4}
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
            <SubmitButton>{hasRoadmap ? "Create new version" : "Generate roadmap"}</SubmitButton>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
