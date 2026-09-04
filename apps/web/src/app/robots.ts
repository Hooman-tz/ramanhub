import type { MetadataRoute } from "next";

import { SITE_URL } from "~/lib/site-url";

/**
 * Public reading surfaces stay crawlable — the feed, the library, published
 * records and profiles are the point. The disallowed paths all bounce a
 * signed-out visitor to `/login`, so crawling them only burns budget on a
 * skeleton.
 */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: "/",
        disallow: [
          "/api/",
          "/office",
          "/lab",
          "/upload",
          "/settings",
          "/onboarding",
          "/login",
        ],
      },
    ],
    sitemap: `${SITE_URL}/sitemap.xml`,
    host: SITE_URL,
  };
}
