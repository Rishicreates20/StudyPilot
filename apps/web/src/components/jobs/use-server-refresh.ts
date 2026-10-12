"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useTransition } from "react";

/** How often a page that shows background work asks the server for its current state. */
export const POLL_INTERVAL_MS = 2_000;

/**
 * Re-renders the page from the server every couple of seconds (`router.refresh()`), so the access
 * token stays on the server and only learner-safe status reaches the browser.
 *
 * A tick is skipped while the previous refresh is still being applied. Without that, a server that
 * takes longer than the interval to render makes every refresh supersede the one before it, and
 * the page never updates at all (it polls busily and shows the same thing).
 */
export function useServerRefresh(): void {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const pendingRef = useRef(pending);

  useEffect(() => {
    pendingRef.current = pending;
  }, [pending]);

  useEffect(() => {
    const timer = setInterval(() => {
      if (!pendingRef.current) startTransition(() => router.refresh());
    }, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [router]);
}
