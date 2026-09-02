import { cookies } from "next/headers";

import { env } from "~/env";

/**
 * Options for `@ramanhub/api-client` calls made from a Server Component:
 * forwards the browser's session cookie so owner-only reads (draft findings,
 * `/auth/session`) work server-side, and pins the base URL to `API_URL`.
 */
export async function serverApiOpts() {
  const jar = await cookies();
  const cookie = jar
    .getAll()
    .map((c) => `${c.name}=${c.value}`)
    .join("; ");
  return {
    baseUrl: env.API_URL,
    headers: cookie ? { cookie } : undefined,
  };
}
