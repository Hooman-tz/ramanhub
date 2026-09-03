"use client";

import { Suspense, useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";

import { getSession } from "@ramanhub/api-client";
import { Button } from "@ramanhub/ui/button";
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
      <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold tracking-tight">Data Lab</h1>
          <p className="text-muted-foreground mt-1 text-sm">
            Your database and your analysis. Prep and unsupervised analysis run
            on this machine, so they&apos;re immediate — but they&apos;re
            exploratory, and hosted analysis runs are still disabled.
          </p>
        </div>
        <Button asChild>
          <Link href="/upload">Add a spectrum</Link>
        </Button>
      </header>
      <Suspense fallback={<Skeleton className="h-[70vh] w-full rounded-2xl" />}>
        <Workbench />
      </Suspense>
    </div>
  );
}
