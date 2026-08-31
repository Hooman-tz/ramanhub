import { Suspense } from "react";
import { notFound } from "next/navigation";

import { getSession, getUserByHandle, isApiError } from "@ramanhub/api-client";

import { BackLink } from "~/components/back-link";
import { ProfileHeader } from "~/components/profile/profile-header";
import { ProfileShell } from "~/components/profile/profile-shell";
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

  return (
    <main className="w-full py-8">
      <div className="mx-auto max-w-5xl px-4">
        <BackLink />
        <div className="mt-4">
          <ProfileHeader profile={profile} isOwner={isOwner} />
        </div>
      </div>

      <Suspense fallback={null}>
        <ProfileShell profile={profile} isOwner={isOwner} />
      </Suspense>
    </main>
  );
}
