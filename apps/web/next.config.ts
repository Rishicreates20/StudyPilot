import path from "node:path";

import type { NextConfig } from "next";

// Docker builds set NEXT_OUTPUT=standalone to produce a minimal self-contained server.
// Vercel and local builds leave it unset. In this npm-workspaces monorepo the trace root
// must be the repository root so shared dependencies are included.
const standalone = process.env.NEXT_OUTPUT === "standalone";

const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
];

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  poweredByHeader: false,
  reactStrictMode: true,
  ...(standalone
    ? { output: "standalone", outputFileTracingRoot: path.resolve(process.cwd(), "../..") }
    : {}),
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

export default nextConfig;
