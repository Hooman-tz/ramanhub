import type { SuggestItem } from "@ramanhub/api-client";

/**
 * Where a search result lives in the web app.
 *
 * Deliberately not part of the API response: mobile will map these kinds to
 * different screens, so the route is the client's decision. Shared between the
 * ⌘K palette and the feed search box so the two cannot disagree about where a
 * result goes.
 *
 * Compounds have no detail route of their own yet, so they open the library's
 * browse tab with the name already searched.
 */
export function hrefForSuggestion(item: SuggestItem): string {
  switch (item.kind) {
    case "compound":
      return `/library?tab=browse&q=${encodeURIComponent(item.title)}`;
    case "spectrum":
      return `/spectra/${item.id}`;
    case "finding":
      return `/findings/${item.id}`;
    case "person":
      return `/u/${item.handle}`;
  }
}
