"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
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
 *
 * `?s=<spectrumId>` pre-selects a sample. The Data Lab links here with it set,
 * so leaving the Lab to identify something does not mean picking your sample a
 * second time. `?q=` pre-fills the browse search, which is how a compound
 * picked in the ⌘K palette arrives — compounds have no detail route yet.
 */
function LibraryView() {
  const params = useSearchParams();
  const session = useQuery({
    queryKey: ["session"],
    queryFn: () => getSession(),
  });

  if (session.isLoading) return <FlowSkeleton />;

  const user = session.data;
  return (
    <IdentifyFlow
      isFullUser={!!user && !user.is_guest}
      initialSpectrumId={params.get("s")}
      initialQuery={params.get("q")}
    />
  );
}

function FlowSkeleton() {
  return (
    <div className="mx-auto w-full max-w-3xl">
      <Skeleton className="h-[60vh] w-full rounded-2xl" />
    </div>
  );
}

export default function LibraryPage() {
  return (
    <div className="px-4 py-6">
      {/* `useSearchParams` opts a route into dynamic rendering unless it sits
          behind a Suspense boundary — same reason `nav-action.tsx` has one. */}
      <Suspense fallback={<FlowSkeleton />}>
        <LibraryView />
      </Suspense>
    </div>
  );
}
