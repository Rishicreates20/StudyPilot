"use client";

import { useState } from "react";

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

/** Interactive demo only: shows focus trapping, Escape to close and focus return. */
export function DialogDemo() {
  const [confirmed, setConfirmed] = useState(false);

  return (
    <div className="flex flex-wrap items-center gap-3">
      <Dialog>
        <DialogTrigger asChild>
          <Button variant="outline">Open dialog</Button>
        </DialogTrigger>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Archive this goal?</DialogTitle>
            <DialogDescription>
              Sample dialog. Focus is trapped inside, Escape closes it, and focus returns to the
              button that opened it.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <DialogClose asChild>
              <Button variant="ghost">Cancel</Button>
            </DialogClose>
            <DialogClose asChild>
              <Button onClick={() => setConfirmed(true)}>Archive</Button>
            </DialogClose>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      {confirmed ? (
        <p role="status" className="text-sm text-muted-foreground">
          Confirmed (nothing was actually archived).
        </p>
      ) : null}
    </div>
  );
}
