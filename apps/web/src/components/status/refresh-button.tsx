"use client";

import { RefreshCwIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useTransition } from "react";

import { Button } from "@/components/ui/button";

/** Re-runs the server-rendered checks on the current page without a full reload. */
export function RefreshButton({ label = "Re-check" }: { label?: string }) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();

  return (
    <Button
      variant="outline"
      loading={pending}
      onClick={() => startTransition(() => router.refresh())}
    >
      {pending ? null : <RefreshCwIcon aria-hidden="true" />}
      {pending ? "Checking" : label}
    </Button>
  );
}
