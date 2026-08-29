import { createEnv } from "@t3-oss/env-nextjs";
import { vercel } from "@t3-oss/env-nextjs/presets-zod";
import { z } from "zod/v4";

export const env = createEnv({
  extends: [vercel()],
  shared: {
    NODE_ENV: z
      .enum(["development", "production", "test"])
      .default("development"),
  },
  /**
   * Server-side env. `API_URL` is the FastAPI base URL the Next.js `/api/*`
   * rewrite forwards to (see next.config.js).
   */
  server: {
    API_URL: z.url().default("http://127.0.0.1:8000"),
  },
  /**
   * Client-side env. Prefix with `NEXT_PUBLIC_`. Kept optional so the browser
   * bundle never needs the backend URL directly — all calls go through `/api`.
   */
  client: {
    NEXT_PUBLIC_API_URL: z.string().optional(),
  },
  experimental__runtimeEnv: {
    NODE_ENV: process.env.NODE_ENV,
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL,
  },
  skipValidation:
    !!process.env.CI || process.env.npm_lifecycle_event === "lint",
});
