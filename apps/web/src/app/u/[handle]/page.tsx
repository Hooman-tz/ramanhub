import Link from "next/link";
import { getFeed } from "@ramanhub/api-client";

import { FeedCard } from "~/components/feed-card";
import { serverApiOpts } from "~/lib/server-api";

export const dynamic = "force-dynamic";

export default async function ProfilePage({
  params,
}: {
  params: Promise<{ handle: string }>;
}) {
  const { handle } = await params;
  // M2: a profile is "this contributor's published work". A richer profile
  // (bio, follower counts, follow button) lands in M4 with the follow graph.
  const items = await getFeed(
    { author: handle, limit: 50 },
    await serverApiOpts(),
  );

  return (
    <main className="mx-auto w-full max-w-2xl px-4 py-8">
      <Link href="/" className="text-muted-foreground text-sm hover:underline">
        ← Feed
      </Link>

      <header className="mt-4 mb-6">
        <h1 className="text-xl font-bold">@{handle}</h1>
        <p className="text-muted-foreground text-sm">
          {items.length} published {items.length === 1 ? "item" : "items"}
        </p>
      </header>

      {items.length === 0 ? (
        <p className="text-muted-foreground rounded-xl border border-dashed p-6 text-center text-sm">
          Nothing published yet.
        </p>
      ) : (
        <div className="space-y-3">
          {items.map((item) => (
            <FeedCard key={`${item.kind}-${item.id}`} item={item} />
          ))}
        </div>
      )}
    </main>
  );
}
