"use client";

import { ContributionGraph } from "~/components/profile/contribution-graph";
import { PinnedGrid } from "~/components/profile/pinned-grid";
import { RecentPosts } from "~/components/profile/profile-tabs";

export function OverviewSection({
  handle,
  isOwner,
  onSeeAllPosts,
}: {
  handle: string;
  isOwner: boolean;
  onSeeAllPosts: () => void;
}) {
  return (
    <div className="space-y-6">
      <ContributionGraph handle={handle} />
      <PinnedGrid handle={handle} isOwner={isOwner} />

      <section className="space-y-2">
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-base font-semibold tracking-tight">
            Recent posts
          </h2>
          <button
            type="button"
            onClick={onSeeAllPosts}
            className="text-primary focus-visible:ring-ring/50 -mx-1 cursor-pointer rounded px-1 py-1 text-sm transition-colors duration-150 outline-none hover:underline focus-visible:ring-[3px] motion-reduce:transition-none"
          >
            View all
          </button>
        </div>
        <RecentPosts handle={handle} />
      </section>
    </div>
  );
}
