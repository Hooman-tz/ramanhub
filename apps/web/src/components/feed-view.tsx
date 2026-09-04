"use client";

import { useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";

import { getFeed, getSession } from "@ramanhub/api-client";
import { cn } from "@ramanhub/ui";
import { Skeleton } from "@ramanhub/ui/skeleton";

import { ComposeFab } from "./compose-fab";
import { Composer } from "./composer";
import { FeedCard } from "./feed-card";

type Tab = "following" | "discover";

/** Parsed feed search: at most one of `tag` / `author` is set. */
interface FeedQuery {
  tag?: string;
  author?: string;
  q?: string;
}

function parseSearch(raw: string): FeedQuery {
  const trimmed = raw.trim();
  if (!trimmed) return {};
  // `@handle` and `#tag` stay exact — they are how you say "this person" or
  // "this tag" and mean it. Anything else is now free text, searched across
  // titles, abstracts, tags and spectrum metadata. It used to be reduced to
  // its first word and matched as a tag, which quietly discarded the rest of
  // whatever you typed.
  if (trimmed.startsWith("@")) {
    return { author: trimmed.slice(1).trim().toLowerCase() };
  }
  if (trimmed.startsWith("#")) {
    return { tag: trimmed.slice(1).trim().toLowerCase() };
  }
  return { q: trimmed };
}


function FeedSkeleton() {
  return (
    <div className="space-y-4" aria-hidden>
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          className="border-border bg-card rounded-xl border p-5 shadow-sm"
        >
          <div className="flex items-center gap-2">
            <Skeleton className="size-6 rounded-full" />
            <Skeleton className="h-3 w-32" />
          </div>
          <Skeleton className="mt-3 h-5 w-3/4" />
          <Skeleton className="mt-2 h-4 w-full" />
          <Skeleton className="mt-1.5 h-4 w-5/6" />
          <div className="mt-4 flex gap-3">
            <Skeleton className="h-4 w-10" />
            <Skeleton className="h-4 w-10" />
            <Skeleton className="h-4 w-16" />
          </div>
        </div>
      ))}
    </div>
  );
}

function EmptyState({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-foreground/70 rounded-xl border border-dashed p-6 text-center text-sm">
      {children}
    </p>
  );
}

export function FeedView({
  showExpandedComposer = false,
}: {
  showExpandedComposer?: boolean;
}) {
  const [tab, setTab] = useState<Tab>("discover");
  const router = useRouter();
  const searchParams = useSearchParams();

  // The search term lives in the URL because the input that sets it is in the
  // header, not on this page. That also makes a filtered feed shareable.
  const rawSearch = searchParams.get("q") ?? "";
  const query = useMemo(() => parseSearch(rawSearch), [rawSearch]);

  const session = useQuery({
    queryKey: ["session"],
    queryFn: () => getSession(),
  });

  const signedIn = !!session.data && !session.data.is_guest;

  const feed = useQuery({
    queryKey: ["feed", tab, query.tag ?? null, query.author ?? null, query.q ?? null],
    queryFn: ({ signal }) =>
      getFeed(
        {
          filter: tab === "following" ? "following" : "all",
          tag: query.tag,
          author: query.author,
          q: query.q,
          limit: 30,
        },
        { signal },
      ),
  });

  function clearSearch() {
    const params = new URLSearchParams(searchParams.toString());
    params.delete("q");
    const qs = params.toString();
    router.replace(qs ? `/?${qs}` : "/", { scroll: false });
  }

  const activeChip = query.author
    ? `author: ${query.author}`
    : query.tag
      ? `#${query.tag}`
      : query.q
        ? `“${query.q}”`
        : null;

  return (
    <main className="mx-auto w-full max-w-2xl px-4 py-8">
      <header className="mb-6">
        <h1 className="text-2xl font-bold tracking-tight">
          Spectra<span className="text-primary">Insight</span>
        </h1>
        <p className="text-muted-foreground mt-1 text-sm">
          What researchers are sharing.
        </p>
      </header>

      {showExpandedComposer && (
        <div className="mb-5">
          <Composer session={session.data ?? null} variant="expanded" />
        </div>
      )}

      {activeChip && (
        <div className="mb-3">
          <button
            type="button"
            onClick={clearSearch}
            className="bg-muted text-foreground/80 hover:text-foreground focus-visible:ring-ring/50 inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium transition-colors focus-visible:ring-[3px] focus-visible:outline-none motion-reduce:transition-none"
          >
            {activeChip}
            <X className="size-3.5" aria-hidden />
            <span className="sr-only">Clear search filter</span>
          </button>
        </div>
      )}

      <div
        className="border-border mb-5 flex gap-1 border-b text-sm"
        aria-label="Feed filter"
      >
        {(["discover", "following"] as Tab[]).map((t) => (
          <button
            key={t}
            type="button"
            aria-pressed={tab === t}
            onClick={() => setTab(t)}
            className={cn(
              "focus-visible:ring-ring/50 -mb-px cursor-pointer rounded-t-md border-b-2 px-3 py-2.5 font-medium capitalize transition-colors focus-visible:ring-[3px] focus-visible:outline-none motion-reduce:transition-none",
              tab === t
                ? "border-primary text-foreground"
                : "text-foreground/70 hover:text-foreground border-transparent",
            )}
          >
            {t}
          </button>
        ))}
      </div>

      {tab === "following" && !signedIn && (
        <EmptyState>
          Sign in and follow some researchers to build this feed.
        </EmptyState>
      )}

      {feed.isLoading && <FeedSkeleton />}
      {feed.isError && (
        <p className="text-destructive rounded-xl border border-dashed p-6 text-center text-sm">
          Could not load the feed.
        </p>
      )}
      {feed.data?.length === 0 && !feed.isLoading && (
        <EmptyState>
          {activeChip
            ? "Nothing matches that search."
            : tab === "following"
              ? "Nothing from people you follow yet."
              : "Nothing here yet — be the first to post."}
        </EmptyState>
      )}

      <div className="space-y-4">
        {feed.data?.map((item) => (
          <FeedCard key={`${item.kind}-${item.id}`} item={item} />
        ))}
      </div>

      <ComposeFab />
    </main>
  );
}
