import type { MetadataRoute } from "next";

import { SITE_URL } from "~/lib/site-url";

/**
 * Static entries only, for now. `/about` is deliberately absent: it is the same
 * page as `/` and canonicalises to it, so nominating both would ask Google to
 * pick a winner we have already picked.
 *
 * Published findings and public profiles belong here too, but they need a
 * public list endpoint and would make this a dynamic route — a separate change.
 */
export default function sitemap(): MetadataRoute.Sitemap {
  return [
    { url: `${SITE_URL}/`, changeFrequency: "daily", priority: 1 },
    { url: `${SITE_URL}/library`, changeFrequency: "weekly", priority: 0.8 },
    { url: `${SITE_URL}/terms`, changeFrequency: "yearly", priority: 0.3 },
    { url: `${SITE_URL}/privacy`, changeFrequency: "yearly", priority: 0.3 },
  ];
}
