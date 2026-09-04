/**
 * The OAuth entry points, shared by the login card and the landing page's
 * closing call to action so the two can never drift apart.
 *
 * These are plain hrefs, not fetches: the browser navigates to `/api/auth/*`,
 * Next rewrites it to FastAPI (see `next.config.js`), and the backend 302s the
 * whole document through the provider and back. That is why a landing page can
 * offer them without shipping any JavaScript.
 */
export interface AuthProvider {
  label: string;
  href: string;
}

export const PROVIDERS: AuthProvider[] = [
  { label: "Continue with Google", href: "/api/auth/login" },
  { label: "Continue with GitHub", href: "/api/auth/github/login" },
  { label: "Continue with ORCID", href: "/api/auth/orcid/login" },
];
