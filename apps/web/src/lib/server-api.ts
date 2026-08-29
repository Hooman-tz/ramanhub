import { cookies } from "next/headers";

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
    baseUrl: process.env.API_URL ?? "http://127.0.0.1:8000",
    headers: cookie ? { cookie } : undefined,
  };
}
