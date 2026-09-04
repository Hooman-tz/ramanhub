import type { Metadata } from "next";

import { Landing } from "~/components/marketing/landing";

const TITLE = "Spectra Insight — an open commons for spectral data";
const DESCRIPTION =
  "Most Raman spectra never leave the instrument PC. Share your data, ask the questions a manual cannot answer, post findings, and publish citable records with their provenance intact.";

export const metadata: Metadata = {
  // `absolute` escapes the root layout's "%s · Spectra Insight" template, which
  // would otherwise append the brand a second time.
  title: { absolute: TITLE },
  description: DESCRIPTION,
  /**
   * `proxy.ts` rewrites `/` to this route for visitors with no session cookie,
   * so two URLs serve identical HTML. Pointing both at `/` is the whole fix for
   * that duplication — `/` self-canonicalises, `/about` defers to it.
   *
   * Never `robots: { index: false }` here. `/` renders this same file, so a
   * noindex would de-index the homepage.
   */
  alternates: { canonical: "/" },
  /**
   * `images` has to be named explicitly here. Declaring an `openGraph` block in
   * a route's metadata replaces the inherited one wholesale, which drops the
   * image Next would otherwise merge in from `app/opengraph-image.tsx` — and
   * this is the page most likely to actually get shared.
   */
  openGraph: {
    type: "website",
    url: "/",
    title: TITLE,
    description: DESCRIPTION,
    siteName: "Spectra Insight",
    images: ["/opengraph-image"],
  },
  twitter: {
    card: "summary_large_image",
    title: TITLE,
    description: DESCRIPTION,
    images: ["/opengraph-image"],
  },
};

export default function AboutPage() {
  return <Landing />;
}
