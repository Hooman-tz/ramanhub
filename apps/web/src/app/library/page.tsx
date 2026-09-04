"use client";

import { useQuery } from "@tanstack/react-query";

import { getSession } from "@ramanhub/api-client";
import { Skeleton } from "@ramanhub/ui/skeleton";

import { IdentifyFlow } from "~/components/library/identify-flow";

/**
 * The reference library as a destination of its own.
 *
 * Unlike `/lab`, this page does not bounce visitors to sign-in. Browsing the
 * corpus is a public endpoint and reads as the front door of the product —
 * turning it away would hide the one part of the platform that is useful
 * before you have uploaded anything. Only the identify flow, which needs your
 * own spectra, asks for an account.
 */
export default function LibraryPage() {
  const session = useQuery({
    queryKey: ["session"],
    queryFn: () => getSession(),
  });

  if (session.isLoading) {
    return (
      <div className="mx-auto max-w-3xl px-4 py-8">
        <Skeleton className="h-[60vh] w-full rounded-2xl" />
      </div>
    );
  }

  const user = session.data;
  return (
    <div className="px-4 py-6">
      <IdentifyFlow isFullUser={!!user && !user.is_guest} />
    </div>
  );
}
