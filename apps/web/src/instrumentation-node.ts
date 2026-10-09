/**
 * Node.js-only startup work. Kept out of instrumentation.ts so bundlers never analyse Node APIs
 * (process.exit) as part of the Edge runtime bundle.
 *
 * Validates the environment at boot so a misconfigured deployment fails immediately with a
 * readable message instead of at the first request. In production the process exits, so the
 * platform reports a failed deploy and restarts are visibly crash-looping; in development the
 * error is rethrown so Next.js shows it on screen.
 */
import { EnvValidationError, validateEnv } from "@/lib/env";

export function validateEnvOrExit() {
  try {
    validateEnv();
  } catch (error) {
    if (error instanceof EnvValidationError && process.env.NODE_ENV === "production") {
      console.error(error.message);
      process.exit(78); // sysexits.h EX_CONFIG, matching the API
    }
    throw error;
  }
}
