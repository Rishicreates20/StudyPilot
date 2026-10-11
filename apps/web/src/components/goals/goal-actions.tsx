"use client";

import {
  ArchiveIcon,
  ArchiveRestoreIcon,
  CircleCheckIcon,
  PauseIcon,
  PencilIcon,
  PlayIcon,
  RotateCcwIcon,
  Trash2Icon,
} from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

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
import type { GoalStatus } from "@/lib/api/server";
import { changeGoalStatusAction, deleteGoalAction } from "@/lib/goals/actions";
import { editGoalPath } from "@/lib/goals/ids";

type GoalActionsProps = {
  goalId: string;
  status: GoalStatus;
};

/**
 * The buttons for what can be done to a goal in its current state. They mirror the lifecycle the
 * API and the database enforce (a goal that can't be paused simply has no Pause button), but the
 * server is what decides: a stale page that offers a button which no longer applies gets a clear
 * "that isn't possible right now" notice, never a silent change.
 *
 * Moves that put a goal out of the way (archive) or cannot be undone (delete) ask first.
 */
export function GoalActions({ goalId, status }: GoalActionsProps) {
  const moveTo = (target: GoalStatus) => changeGoalStatusAction.bind(null, goalId, target);

  return (
    <div className="flex flex-wrap gap-2">
      {status !== "archived" ? (
        <Button asChild variant="outline">
          <Link href={editGoalPath(goalId)}>
            <PencilIcon aria-hidden="true" />
            Edit
          </Link>
        </Button>
      ) : null}

      {status === "active" ? (
        <StatusButton action={moveTo("paused")} icon={<PauseIcon aria-hidden="true" />}>
          Pause
        </StatusButton>
      ) : null}
      {status === "paused" ? (
        <StatusButton action={moveTo("active")} icon={<PlayIcon aria-hidden="true" />}>
          Resume
        </StatusButton>
      ) : null}
      {status === "active" || status === "paused" ? (
        <StatusButton
          action={moveTo("completed")}
          icon={<CircleCheckIcon aria-hidden="true" />}
          variant="default"
        >
          Mark complete
        </StatusButton>
      ) : null}
      {status === "completed" ? (
        <StatusButton action={moveTo("active")} icon={<RotateCcwIcon aria-hidden="true" />}>
          Reopen
        </StatusButton>
      ) : null}

      {status === "archived" ? (
        <StatusButton
          action={moveTo("active")}
          icon={<ArchiveRestoreIcon aria-hidden="true" />}
          variant="default"
        >
          Restore
        </StatusButton>
      ) : (
        <ConfirmAction
          triggerLabel="Archive"
          triggerIcon={<ArchiveIcon aria-hidden="true" />}
          title="Archive this goal?"
          description="It leaves your dashboard but nothing is lost. You can restore it from the archive at any time."
          confirmLabel="Archive goal"
          action={moveTo("archived")}
        />
      )}

      {status === "archived" ? (
        <ConfirmAction
          triggerLabel="Delete permanently"
          triggerIcon={<Trash2Icon aria-hidden="true" />}
          title="Delete this goal permanently?"
          description="The goal and everything attached to it will be removed for good. This cannot be undone."
          confirmLabel="Delete forever"
          action={deleteGoalAction.bind(null, goalId)}
          destructive
        />
      ) : null}
    </div>
  );
}

function StatusButton({
  action,
  icon,
  children,
  variant = "outline",
}: {
  action: () => Promise<void>;
  icon: ReactNode;
  children: ReactNode;
  variant?: "outline" | "default";
}) {
  return (
    <form action={action}>
      <SubmitButton variant={variant}>
        {icon}
        {children}
      </SubmitButton>
    </form>
  );
}

type ConfirmActionProps = {
  triggerLabel: string;
  triggerIcon: ReactNode;
  title: string;
  description: string;
  confirmLabel: string;
  action: () => Promise<void>;
  destructive?: boolean;
};

/** A button that opens a dialog asking "are you sure?" before running a Server Action. */
function ConfirmAction({
  triggerLabel,
  triggerIcon,
  title,
  description,
  confirmLabel,
  action,
  destructive = false,
}: ConfirmActionProps) {
  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button variant={destructive ? "destructive" : "outline"}>
          {triggerIcon}
          {triggerLabel}
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <form action={action}>
          <DialogFooter>
            <DialogClose asChild>
              <Button type="button" variant="outline">
                Cancel
              </Button>
            </DialogClose>
            <SubmitButton variant={destructive ? "destructive" : "default"}>
              {confirmLabel}
            </SubmitButton>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
