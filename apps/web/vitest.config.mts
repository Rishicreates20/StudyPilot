import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    css: false,
    restoreMocks: true,
    // Form tests type character by character through user-event. On a busy machine (or a CI
    // runner with 30 test files in flight) that can pass the 5 s default without anything being
    // wrong, so allow generous headroom instead of re-running flaky failures.
    testTimeout: 20_000,
  },
});
