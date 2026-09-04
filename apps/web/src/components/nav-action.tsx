"use client";

import { useEffect, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Plus, Search, X } from "lucide-react";

import { suggest } from "@ramanhub/api-client";
import { Combobox } from "@ramanhub/ui/combobox";

import { NewDatasetDialog } from "~/components/lab/data-management";
import { useDebounced } from "~/hooks/use-debounced";
import { ComposeFab } from "./compose-fab";
import { hrefForSuggestion } from "./search/href-for-suggestion";

/**
 * The header's primary action, which depends on where you are.
 *
 * A single fixed "New post" button was wrong everywhere except the office: in
 * the lab the thing you want to make is a dataset, and on the feed the thing
 * you want isn't a button at all — it's search, which used to sit in the middle
 * of the page pushing the actual feed down.
 */

/**
 * Feed search, lifted out of the page body into the header.
 *
 * The term lives in the URL rather than in component state so the header and
 * the feed stay in agreement without sharing a store — and a filtered feed
 * becomes a link you can send someone.
 */
function FeedSearch() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const urlQuery = searchParams.get("q") ?? "";
  const [value, setValue] = useState(urlQuery);

  // Follow the URL when it changes from elsewhere (a tag chip, back/forward),
  // but never fight the user mid-keystroke.
  useEffect(() => {
    setValue(urlQuery);
  }, [urlQuery]);

  const submit = (next: string) => {
    const params = new URLSearchParams(searchParams.toString());
    if (next.trim()) params.set("q", next.trim());
    else params.delete("q");
    const qs = params.toString();
    router.replace(qs ? `/?${qs}` : "/", { scroll: false });
  };

  const debounced = useDebounced(value.trim(), 200);
  const results = useQuery({
    queryKey: ["suggest", debounced],
    queryFn: ({ signal }) => suggest({ q: debounced, limit: 4 }, { signal }),
    enabled: debounced.length >= 2,
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });

  const items = useMemo(
    () =>
      (results.data?.groups ?? []).flatMap((g) =>
        g.items.map((item) => ({ ...item, group: g.label })),
      ),
    [results.data],
  );

  const clear = () => {
    setValue("");
    submit("");
  };

  return (
    <form
      role="search"
      onSubmit={(e) => {
        e.preventDefault();
        submit(value);
      }}
      className="min-w-0 flex-1 sm:max-w-xs"
    >
      <label htmlFor="nav-feed-search" className="sr-only">
        Search the feed
      </label>
      <Combobox
        items={items}
        value={value}
        onValueChange={setValue}
        // A picked suggestion goes to that thing; typing and pressing Enter
        // still searches the feed, which is what the box has always done.
        onSelect={(item) => {
          setValue("");
          router.push(hrefForSuggestion(item));
        }}
        onSubmitRaw={submit}
        onEscape={clear}
        listboxId="nav-feed-search-suggestions"
        inputProps={{
          id: "nav-feed-search",
          type: "search",
          placeholder: "Search the feed — or @author, #tag",
          className:
            "placeholder:text-muted-foreground w-full min-w-0 bg-transparent py-1 text-sm focus:outline-none [&::-webkit-search-cancel-button]:hidden",
        }}
        renderItem={(item) => (
          <span className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm">
            <span className="min-w-0 flex-1 truncate">{item.title}</span>
            {item.subtitle && (
              <span className="text-muted-foreground shrink-0 truncate text-xs">
                {item.subtitle}
              </span>
            )}
          </span>
        )}
      >
        {(input) => (
          <div className="border-border/70 bg-card/60 focus-within:border-primary/40 flex min-w-0 items-center gap-1.5 rounded-xl border px-2.5 py-1 backdrop-blur transition-colors motion-reduce:transition-none">
            <Search className="text-muted-foreground size-4 shrink-0" aria-hidden />
            {input}
            {value && (
              <button
                type="button"
                onClick={clear}
                aria-label="Clear search"
                className="bg-muted text-muted-foreground hover:text-foreground flex size-5 shrink-0 items-center justify-center rounded-full"
              >
                <X className="size-3" aria-hidden />
              </button>
            )}
          </div>
        )}
      </Combobox>
    </form>
  );
}

function NewDatasetAction() {
  const [open, setOpen] = useState(false);
  const router = useRouter();

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="text-foreground/80 hover:text-foreground hover:bg-muted focus-visible:ring-ring/50 inline-flex min-h-11 items-center gap-1.5 rounded-md px-2.5 text-sm font-medium transition-colors focus-visible:ring-[3px] focus-visible:outline-none motion-reduce:transition-none"
      >
        <Plus className="size-4" aria-hidden />
        <span className="sr-only md:not-sr-only">New dataset</span>
      </button>
      <NewDatasetDialog
        open={open}
        onOpenChange={setOpen}
        // Open the folder that was just made, so creating it and filling it are
        // one motion rather than two.
        onCreated={(dataset) =>
          router.push(`/lab?tab=workbench&mode=database&d=${dataset.id}`)
        }
      />
    </>
  );
}

export function NavAction({ isFullUser }: { isFullUser: boolean }) {
  const pathname = usePathname();

  // Search is useful signed out too; the create actions are not.
  if (pathname === "/") return <FeedSearch />;
  if (!isFullUser) return null;
  if (pathname.startsWith("/lab") || pathname.startsWith("/upload")) {
    return <NewDatasetAction />;
  }
  // The Library is a read-and-identify surface; a "new post" button there
  // would be an action about a different object entirely.
  if (pathname.startsWith("/library")) return null;
  return <ComposeFab variant="nav-button" />;
}
