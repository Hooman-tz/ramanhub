"use client";

import { useQuery } from "@tanstack/react-query";

import { getSession } from "@ramanhub/api-client";

/**
 * The one shared `["session"]` query. Every consumer reads the same TanStack
 * cache entry, so an extra caller costs no extra request.
 *
 * `getSession()` resolves to `null` on 401 rather than throwing, so "signed
 * out" is a successful result, not an error.
 */
export function useSession() {
  const query = useQuery({ queryKey: ["session"], queryFn: () => getSession() });

  const user = query.data ?? null;
  const isFullUser = !!user && !user.is_guest;

  return {
    user,
    isFullUser,
    /**
     * True only once the query has actually answered — deliberately not the
     * inverse of `isFullUser`.
     *
     * Nav links are hidden on this, so while the query is pending every link
     * still renders and signed-in users see no change from before. Gating on
     * `isFullUser` instead would give them a visible nav-width jump on every
     * page load, which is strictly worse: they are the people who see the nav
     * most.
     */
    isKnownSignedOut: !query.isPending && !isFullUser,
  };
}
