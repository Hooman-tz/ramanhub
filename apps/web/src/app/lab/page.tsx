"use client";

import { Suspense, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";

import { getSession } from "@ramanhub/api-client";
import { Skeleton } from "@ramanhub/ui/skeleton";

import { Workbench } from "~/components/profile/workbench";

export default function LabPage() {
  const router = useRouter();
  const session = useQuery({
    queryKey: ["session"],
    queryFn: () => getSession(),
  });

  const user = session.data;
  const ready = !session.isLoading;
  const blocked = ready && (!user || user.is_guest);

  useEffect(() => {
    if (blocked) router.replace("/login?next=/lab");
  }, [blocked, router]);

  if (!ready || blocked) {
    return (
      <div className="mx-auto max-w-5xl px-4 py-8">
        <Skeleton className="h-[70vh] w-full rounded-2xl" />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-[1500px] px-4 py-6">
      <header className="mb-4">
        <h1 className="text-xl font-bold tracking-tight">My Lab</h1>
        <p className="text-muted-foreground mt-1 text-sm">
          Your SpectraBase and the processing toolbox. The public Commons and
          the analysis toolbox arrive with their backend endpoints.
        </p>
      </header>
      <Suspense fallback={<Skeleton className="h-[70vh] w-full rounded-2xl" />}>
        <Workbench />
      </Suspense>
    </div>
  );
}
