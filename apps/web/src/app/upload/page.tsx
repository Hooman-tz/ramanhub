"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";

import { getSession } from "@ramanhub/api-client";
import { Skeleton } from "@ramanhub/ui/skeleton";

import { UploadWizard } from "~/components/upload/upload-wizard";

export default function UploadPage() {
  const router = useRouter();
  const session = useQuery({
    queryKey: ["session"],
    queryFn: () => getSession(),
  });

  const user = session.data;
  const ready = !session.isLoading;
  // Guests can technically upload, but they can never publish and guest
  // migration does not carry their work over, so ask them to sign in first.
  const blocked = ready && (!user || user.is_guest);

  useEffect(() => {
    if (blocked) router.replace("/login?next=/upload");
  }, [blocked, router]);

  if (!ready || blocked) {
    return (
      <div className="mx-auto w-full max-w-2xl px-4 py-10">
        <Skeleton className="h-80 w-full rounded-2xl" />
      </div>
    );
  }

  return (
    <main className="mx-auto w-full max-w-2xl space-y-6 px-4 py-10">
      <header>
        <h1 className="text-2xl font-bold tracking-tight">Add a spectrum</h1>
        <p className="text-muted-foreground mt-1 text-sm">
          Upload a raw vendor file. It stays private as a draft until you
          publish it.
        </p>
      </header>
      <UploadWizard />
    </main>
  );
}
