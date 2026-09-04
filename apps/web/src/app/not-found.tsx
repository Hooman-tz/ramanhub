import Link from "next/link";

import { Button } from "@ramanhub/ui/button";

/**
 * Unmatched URLs resolve at the root segment, outside the `(app)` group — so
 * this renders without the app nav and has to stand on its own. Before the
 * route-group split, Next's built-in 404 inherited the nav from the root
 * layout; this replaces it.
 */
export default function NotFound() {
  return (
    <main className="mx-auto flex min-h-[60vh] w-full max-w-md flex-col items-center justify-center px-4 text-center">
      <div className="border-border bg-card w-full rounded-2xl border p-6">
        <h1 className="text-lg font-semibold tracking-tight">
          This page doesn&apos;t exist
        </h1>
        <p className="text-foreground/70 mt-1 text-sm">
          The link may be broken, or the record may have been unpublished.
        </p>
        <div className="mt-5 flex justify-center gap-2">
          <Button asChild>
            <Link href="/">Go home</Link>
          </Button>
          <Button variant="outline" asChild>
            <Link href="/library">Browse the library</Link>
          </Button>
        </div>
      </div>
    </main>
  );
}
