"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Plus, Search, X } from "lucide-react";

import { NewDatasetDialog } from "~/components/lab/data-management";
import { ComposeFab } from "./compose-fab";

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

  return (
    <form
      role="search"
      onSubmit={(e) => {
        e.preventDefault();
        submit(value);
      }}
      className="border-border/70 bg-card/60 focus-within:border-primary/40 flex min-w-0 flex-1 items-center gap-1.5 rounded-xl border px-2.5 py-1 backdrop-blur transition-colors motion-reduce:transition-none sm:max-w-xs"
    >
      <Search className="text-muted-foreground size-4 shrink-0" aria-hidden />
      <label htmlFor="nav-feed-search" className="sr-only">
        Search the feed
      </label>
      <input
        id="nav-feed-search"
        type="search"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            e.preventDefault();
            setValue("");
            submit("");
          }
        }}
        placeholder="Search — @author or #tag"
        className="placeholder:text-muted-foreground w-full min-w-0 bg-transparent py-1 text-sm focus:outline-none [&::-webkit-search-cancel-button]:hidden"
      />
      {value && (
        <button
          type="button"
          onClick={() => {
            setValue("");
            submit("");
          }}
          aria-label="Clear search"
          className="bg-muted text-muted-foreground hover:text-foreground flex size-5 shrink-0 items-center justify-center rounded-full"
        >
          <X className="size-3" aria-hidden />
        </button>
      )}
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
  return <ComposeFab variant="nav-button" />;
}
