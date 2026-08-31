"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { getFeed, getSession } from "@ramanhub/api-client";
import { cn } from "@ramanhub/ui";
import { Skeleton } from "@ramanhub/ui/skeleton";

import { Composer } from "./composer";
import { FeedCard } from "./feed-card";

type Tab = "following" | "discover";

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

export function FeedView() {
  const [tab, setTab] = useState<Tab>("discover");

  const session = useQuery({
    queryKey: ["session"],
    queryFn: () => getSession(),
  });

  const signedIn = !!session.data && !session.data.is_guest;

  const feed = useQuery({
    queryKey: ["feed", tab],
    queryFn: () =>
      getFeed({ filter: tab === "following" ? "following" : "all", limit: 30 }),
  });

  return (
    <main className="mx-auto w-full max-w-2xl px-4 py-8">
      <header className="mb-6">
        <h1 className="text-2xl font-bold tracking-tight">
          Spectra<span className="text-primary">Insight</span>
        </h1>
        <p className="text-foreground/70 mt-1 text-sm">
          What researchers are sharing.
        </p>
      </header>

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

      <div className="mb-5">
        <Composer session={session.data ?? null} />
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
          {tab === "following"
            ? "Nothing from people you follow yet."
            : "Nothing here yet — be the first to post."}
        </EmptyState>
      )}

      <div className="space-y-4">
        {feed.data?.map((item) => (
          <FeedCard key={`${item.kind}-${item.id}`} item={item} />
        ))}
      </div>
    </main>
  );
}
