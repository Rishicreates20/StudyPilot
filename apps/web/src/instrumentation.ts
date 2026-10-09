/** Runs once when the Next.js server starts. Node-only work lives in instrumentation-node.ts. */
export async function register() {
  if (process.env.NEXT_RUNTIME === "nodejs") {
    const { validateEnvOrExit } = await import("./instrumentation-node");
    validateEnvOrExit();
  }
}
