"use client";

/**
 * Route-segment error boundary. Catches render/runtime errors thrown by any
 * page under `app/` (including server components that rethrow a non-404 API
 * error). Users see one calm line and a retry; the real error goes to the
 * console (and, later, an error reporter) — never onto the screen.
 */
import { useEffect } from "react";
import Link from "next/link";

import { Button } from "@ramanhub/ui/button";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("[route error]", error);
  }, [error]);

  return (
    <main className="mx-auto flex min-h-[60vh] w-full max-w-md flex-col items-center justify-center px-4 text-center">
      <div className="border-border bg-card w-full rounded-2xl border p-6">
        <h1 className="text-lg font-semibold tracking-tight">
          Something went wrong
        </h1>
        <p className="text-foreground/70 mt-1 text-sm">
          This page hit an unexpected error. You can try again, or head back to
          the feed.
        </p>
        <div className="mt-5 flex justify-center gap-2">
          <Button onClick={reset}>Try again</Button>
          <Button variant="outline" asChild>
            <Link href="/">Go home</Link>
          </Button>
        </div>
        {error.digest ? (
          <p className="text-foreground/40 mt-4 font-mono text-[11px]">
            ref {error.digest}
          </p>
        ) : null}
      </div>
    </main>
  );
}
