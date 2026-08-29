import Link from "next/link";
import { notFound } from "next/navigation";
import {
  getFeed,
  getFollowStatus,
  getUserByHandle,
  isApiError,
} from "@ramanhub/api-client";
import type { FollowStatus } from "@ramanhub/api-client";

import { FeedCard } from "~/components/feed-card";
import { FollowButton } from "~/components/follow-button";
import { serverApiOpts } from "~/lib/server-api";

export const dynamic = "force-dynamic";

export default async function ProfilePage({
  params,
}: {
  params: Promise<{ handle: string }>;
}) {
  const { handle } = await params;
  const opts = await serverApiOpts();

  let profile;
  try {
    profile = await getUserByHandle(handle, opts);
  } catch (e) {
    if (isApiError(e) && e.status === 404) notFound();
    throw e;
  }

  let followStatus: FollowStatus | undefined;
  try {
    followStatus = await getFollowStatus(handle, opts);
  } catch {
    /* client island will fetch */
  }

  const items = await getFeed({ author: handle, limit: 50 }, opts);

  const name = profile.display_name ?? `@${handle}`;

  return (
    <main className="mx-auto w-full max-w-2xl px-4 py-8">
      <Link href="/" className="text-muted-foreground text-sm hover:underline">
        ← Feed
      </Link>

      <header className="mt-4 mb-6 flex items-start gap-4">
        {profile.avatar_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={profile.avatar_url}
            alt=""
            className="size-16 rounded-full object-cover"
          />
        ) : (
          <span className="bg-primary/10 text-primary inline-flex size-16 items-center justify-center rounded-full text-lg font-semibold">
            {name.slice(0, 2).toUpperCase()}
          </span>
        )}

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-xl font-bold">{name}</h1>
            {profile.orcid_verified && (
              <span
                className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-2 py-0.5 text-xs font-medium text-emerald-600 dark:text-emerald-400"
                title={profile.orcid_id ?? "ORCID verified"}
              >
                ✓ ORCID
              </span>
            )}
          </div>
          <p className="text-muted-foreground text-sm">@{handle}</p>
          {profile.affiliation && (
            <p className="text-muted-foreground mt-0.5 text-sm">
              {profile.affiliation}
            </p>
          )}
          {profile.bio && (
            <p className="text-foreground/90 mt-2 text-sm whitespace-pre-wrap">
              {profile.bio}
            </p>
          )}

          <div className="text-muted-foreground mt-2 flex gap-4 text-sm">
            <span>
              <strong className="text-foreground">{profile.followers}</strong>{" "}
              followers
            </span>
            <span>
              <strong className="text-foreground">{profile.following}</strong>{" "}
              following
            </span>
          </div>

          {profile.research_interests &&
            profile.research_interests.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-1.5 text-xs">
                {profile.research_interests.map((t) => (
                  <span key={t} className="bg-muted rounded px-1.5 py-0.5">
                    #{t}
                  </span>
                ))}
              </div>
            )}

          <div className="mt-3">
            <FollowButton handle={handle} initial={followStatus} />
          </div>
        </div>
      </header>

      <h2 className="text-muted-foreground mb-3 text-sm font-semibold">
        {items.length} published {items.length === 1 ? "item" : "items"}
      </h2>

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
