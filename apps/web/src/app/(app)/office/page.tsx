"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";

import { getSession } from "@ramanhub/api-client";
import { Skeleton } from "@ramanhub/ui/skeleton";

import { OfficeView } from "~/components/office/office-view";

export default function OfficePage() {
  const router = useRouter();
  const session = useQuery({
    queryKey: ["session"],
    queryFn: () => getSession(),
  });

  const user = session.data;
  const ready = !session.isLoading;
  const handle = user?.profile_handle ?? null;
  const blocked = ready && (!user || user.is_guest || !handle);

  useEffect(() => {
    if (blocked) router.replace("/login?next=/office");
  }, [blocked, router]);

  if (!ready || blocked || !handle) {
    return (
      <main className="mx-auto w-full max-w-3xl space-y-4 px-4 py-8">
        <Skeleton className="h-40 w-full rounded-2xl" />
        <Skeleton className="h-52 w-full rounded-2xl" />
        <Skeleton className="h-40 w-full rounded-2xl" />
      </main>
    );
  }

  return <OfficeView handle={handle} />;
}
