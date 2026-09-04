import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

/**
 * Anonymous visitors to `/` get the marketing landing page; anyone carrying a
 * `session` cookie keeps the feed, exactly as before.
 *
 * Next 16 renamed this file convention from `middleware` to `proxy` — the
 * export must be named `proxy`, and it always runs on the Node.js runtime.
 *
 * This is a REWRITE, not a redirect. The browser URL stays `/`, so the root
 * stays the URL we hand out, share and let Google index; `/about` renders the
 * same route and names `/` as its canonical, which is what dedupes the two. A
 * redirect would put Googlebot — which never carries cookies — on a 30x for
 * every homepage crawl and index `/about` instead. This is ordinary
 * cookie-based personalisation, not cloaking: a crawler sees precisely what any
 * signed-out human sees.
 *
 * Cookie *presence* is not validation, deliberately. The cookie's `max_age` and
 * the JWT's `exp` both derive from `JWT_EXPIRES_HOURS`, so the browser drops the
 * cookie at roughly the moment the token stops working. In the residual window
 * a stale visitor sees the feed shell and its client-side `getSession()` returns
 * null — which is exactly what a signed-out visitor already got at `/`. Nothing
 * private leaks either way: `/` is prerendered identical HTML for everyone and
 * all user data arrives client-side over `/api/*`.
 */
const SESSION_COOKIE = "session";
const LANDING_PATH = "/about";

export function proxy(request: NextRequest) {
  let res: NextResponse;

  if (request.cookies.has(SESSION_COOKIE)) {
    res = NextResponse.next();
  } else {
    // `clone()` preserves the query string, including the `?_rsc=` marker Next
    // appends to client-side prefetch and navigation requests.
    const url = request.nextUrl.clone();
    url.pathname = LANDING_PATH;
    res = NextResponse.rewrite(url);
  }

  /**
   * `/` now serves two different documents depending on a cookie, so no shared
   * cache may store it. `private` is what actually enforces that; `no-cache`
   * (revalidate before reuse, rather than `no-store`) keeps the document
   * eligible for the back/forward cache, and we lose nothing by revalidating a
   * page that was prerendered anyway.
   *
   * `Vary: Cookie` would be the textbook addition here and is deliberately
   * absent: Next overwrites `Vary` on prerendered responses with its own
   * `rsc, next-router-state-tree, …` list, and neither `set` nor `append`
   * survives — measured against `next start`, not assumed. Other headers set
   * here (including this `Cache-Control`) do survive. `private` covers us
   * regardless, since a shared cache must not store the response at all.
   */
  res.headers.set("Cache-Control", "private, no-cache, must-revalidate");

  return res;
}

export const config = {
  /**
   * `/` and nothing else. An exact literal means there is no negative-lookahead
   * regex to get subtly wrong, and the `/api/:path*` → FastAPI rewrite in
   * `next.config.js` is structurally unreachable from here.
   */
  matcher: ["/"],
};
