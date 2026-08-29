"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getFeed, getSession } from "@ramanhub/api-client";

import { cn } from "@ramanhub/ui";

import { Composer } from "./composer";
import { FeedCard } from "./feed-card";

type Tab = "following" | "discover";

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
        <p className="text-muted-foreground text-sm">
          What researchers are sharing.
        </p>
      </header>

      <div className="border-border mb-4 flex gap-1 border-b text-sm">
        {(["discover", "following"] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={cn(
              "-mb-px border-b-2 px-3 py-2 font-medium capitalize transition-colors",
              tab === t
                ? "border-primary text-foreground"
                : "text-muted-foreground border-transparent hover:text-foreground",
            )}
          >
            {t}
          </button>
        ))}
      </div>

      <div className="mb-4">
        <Composer session={session.data ?? null} />
      </div>

      {tab === "following" && !signedIn && (
        <p className="text-muted-foreground rounded-xl border border-dashed p-6 text-center text-sm">
          Sign in and follow some researchers to build this feed.
        </p>
      )}

      {feed.isLoading && (
        <p className="text-muted-foreground p-6 text-center text-sm">Loading…</p>
      )}
      {feed.isError && (
        <p className="text-destructive p-6 text-center text-sm">
          Could not load the feed.
        </p>
      )}
      {feed.data?.length === 0 && !feed.isLoading && (
        <p className="text-muted-foreground rounded-xl border border-dashed p-6 text-center text-sm">
          {tab === "following"
            ? "Nothing from people you follow yet."
            : "Nothing here yet — be the first to post."}
        </p>
      )}

      <div className="space-y-3">
        {feed.data?.map((item) => (
          <FeedCard key={`${item.kind}-${item.id}`} item={item} />
        ))}
      </div>
    </main>
  );
}
