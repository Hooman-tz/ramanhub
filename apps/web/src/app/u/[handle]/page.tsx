import { Suspense } from "react";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getSession, getUserByHandle, isApiError } from "@ramanhub/api-client";

import { ContributionGraph } from "~/components/profile/contribution-graph";
import { PinnedGrid } from "~/components/profile/pinned-grid";
import { ProfileHeader } from "~/components/profile/profile-header";
import { ProfileTabs } from "~/components/profile/profile-tabs";
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

  const session = await getSession(opts);
  const isOwner = !!session && session.id === profile.id;
  const h = profile.profile_handle ?? handle;

  return (
    <main className="mx-auto w-full max-w-4xl space-y-6 px-4 py-8">
      <Link href="/" className="text-muted-foreground text-sm hover:underline">
        ← Feed
      </Link>

      <ProfileHeader profile={profile} isOwner={isOwner} />
      <ContributionGraph handle={h} />
      <PinnedGrid handle={h} isOwner={isOwner} />
      <Suspense fallback={null}>
        <ProfileTabs profile={profile} isOwner={isOwner} />
      </Suspense>
    </main>
  );
}
