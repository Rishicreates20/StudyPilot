"use client";

import { useServerRefresh } from "@/components/jobs/use-server-refresh";

/**
 * Keeps a page that lists documents fresh while any of them is still being processed. Render it
 * only while there is work in progress, so a finished page stops asking the server.
 */
export function AutoRefresh() {
  useServerRefresh();
  return null;
}
