import { env } from "~/env";

/**
 * This app's own public origin (ADR-014: `spectra-in.site` is the product site,
 * `raman.spectra-in.site` is this app).
 *
 * `env.SITE_URL` is typed as a required string, but env validation is skipped on
 * CI builds so it is `undefined` there in practice — hence the cast and the
 * fallback. `new URL(undefined)` would crash the build.
 *
 * Shared by `layout.tsx` (`metadataBase`), `robots.ts` and `sitemap.ts` so the
 * three can never disagree about what this site is called.
 */
export const SITE_URL =
  (env.SITE_URL as string | undefined) ?? "https://raman.spectra-in.site";
