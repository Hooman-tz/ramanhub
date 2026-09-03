"use client";

import { useQuery } from "@tanstack/react-query";

import { getUserByHandle } from "@ramanhub/api-client";
import { Card } from "@ramanhub/ui/card";
import { Skeleton } from "@ramanhub/ui/skeleton";

import { ContributionGraph } from "~/components/profile/contribution-graph";
import { ProfileHeader } from "~/components/profile/profile-header";
import { CollabNetwork } from "./collab-network";
import { RecentActivity } from "./recent-activity";
import { SavedPosts } from "./saved-posts";
import { ProjectStatus } from "./project-status";

const STAT_KEYS = [
  ["spectrum_count", "Spectra"],
  ["finding_count", "Findings"],
  ["doi_linked", "DOI-linked"],
  ["votes_received", "Votes"],
  ["followers", "Followers"],
] as const;

export function OfficeView({ handle }: { handle: string }) {
  const profile = useQuery({
    queryKey: ["profile", handle],
    queryFn: () => getUserByHandle(handle),
  });

  return (
    <main className="mx-auto w-full max-w-3xl space-y-5 px-4 py-8">
      {profile.data ? (
        <>
          <ProfileHeader profile={profile.data} isOwner />
          <div className="grid grid-cols-3 gap-2 sm:grid-cols-5">
            {STAT_KEYS.map(([key, label]) => (
              <Card
                key={key}
                className="border-border bg-secondary/60 gap-0 p-2.5 text-center"
              >
                <div className="text-sm font-bold">
                  {profile.data[key].toLocaleString()}
                </div>
                <div className="text-muted-foreground text-[10px]">{label}</div>
              </Card>
            ))}
          </div>
        </>
      ) : profile.isError ? (
        <Card className="text-muted-foreground p-6 text-center text-sm">
          Could not load your profile.
        </Card>
      ) : (
        <>
          <Skeleton className="h-44 w-full rounded-2xl" />
          <Skeleton className="h-16 w-full rounded-2xl" />
        </>
      )}

      <ContributionGraph handle={handle} />
      <ProjectStatus />
      <RecentActivity />
      <SavedPosts handle={handle} />
      <CollabNetwork handle={handle} />
    </main>
  );
}
