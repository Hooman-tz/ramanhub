import { fileURLToPath } from "node:url";

import { createJiti } from "jiti";

const jiti = createJiti(import.meta.url);

/** Monorepo root, so Turbopack doesn't infer it from a stray lockfile elsewhere */
const workspaceRoot = fileURLToPath(new URL("../..", import.meta.url));

// Import env files to validate at build time. Use jiti so we can load .ts files in here.
await jiti.import("./src/env");

/**
 * The FastAPI backend base URL. In dev this is the local uvicorn server; in
 * production it is api.spectra-in.site (or the Replit/Render URL). The browser
 * always talks to `/api/*` on the Next.js origin — the rewrite below forwards
 * to FastAPI — so the existing `samesite=lax` session cookie keeps working.
 */
const API_URL = process.env.API_URL ?? "http://127.0.0.1:8000";

/** @type {import("next").NextConfig} */
const config = {
  turbopack: { root: workspaceRoot },
  outputFileTracingRoot: workspaceRoot,

  /** Enables hot reloading for local packages without a build step */
  transpilePackages: [
    "@ramanhub/api-client",
    "@ramanhub/ui",
    "@ramanhub/validators",
  ],

  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_URL}/:path*` }];
  },

  /** We already do linting and typechecking as separate tasks in CI */
  typescript: { ignoreBuildErrors: true },
};

export default config;
