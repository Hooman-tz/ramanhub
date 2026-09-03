"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";

import { getSession } from "@ramanhub/api-client";
import { cn } from "@ramanhub/ui";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@ramanhub/ui/dialog";

import { Composer } from "./composer";

/**
 * One component, two triggers, independent dialog state:
 * - `fab`        — floating action button, bottom-right of the feed page.
 * - `nav-button` — compact inline button in the top nav (full users only).
 *
 * Each mounted instance keeps its own `open` state — they don't share a store,
 * which is fine: only one is ever visible/interacted with at a time.
 */
export function ComposeFab({
  variant = "fab",
}: {
  variant?: "fab" | "nav-button";
}) {
  const [open, setOpen] = useState(false);
  const session = useQuery({
    queryKey: ["session"],
    queryFn: () => getSession(),
  });
  const user = session.data ?? null;
  const isFullUser = !!user && !user.is_guest;

  // The nav affordance is for signed-in full users only. The FAB always shows
  // (guests get the sign-in nudge inside the dialog).
  if (variant === "nav-button" && !isFullUser) return null;

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      {variant === "fab" ? (
        <button
          type="button"
          onClick={() => setOpen(true)}
          aria-label="New post"
          className={cn(
            "bg-primary text-primary-foreground focus-visible:ring-ring/50 fixed z-40 flex size-14 items-center justify-center rounded-full shadow-lg transition-transform hover:scale-105 focus-visible:ring-[3px] focus-visible:outline-none motion-reduce:transition-none",
            // Clear the mobile bottom nav (h-14 + safe area); normal offset from md up.
            "bottom-[calc(4.5rem+env(safe-area-inset-bottom))] md:bottom-[max(1.5rem,env(safe-area-inset-bottom))]",
            // The theme toggle is bottom-left on mobile and bottom-right from
            // md up, so the FAB has to swap sides to avoid sitting on top of
            // it — which it did on desktop.
            "right-6 md:right-auto md:left-6",
          )}
        >
          <Plus className="size-6" aria-hidden />
        </button>
      ) : (
        <button
          type="button"
          onClick={() => setOpen(true)}
          aria-label="New post"
          className="text-foreground/80 hover:text-foreground hover:bg-muted focus-visible:ring-ring/50 inline-flex min-h-11 items-center gap-1.5 rounded-md px-2.5 text-sm font-medium transition-colors focus-visible:ring-[3px] focus-visible:outline-none motion-reduce:transition-none"
        >
          <Plus className="size-4" aria-hidden />
          <span className="sr-only md:not-sr-only">New post</span>
        </button>
      )}

      <DialogContent>
        <DialogHeader>
          <DialogTitle>New post</DialogTitle>
        </DialogHeader>
        <Composer
          session={user}
          variant="dialog"
          onPosted={() => setOpen(false)}
        />
      </DialogContent>
    </Dialog>
  );
}
