"use client";

import { Check, Lock } from "lucide-react";

import { cn } from "@ramanhub/ui";
import { Card } from "@ramanhub/ui/card";

/**
 * One numbered step in the Library's identify flow.
 *
 * The flow is linear on purpose: pick a spectrum, look at its bands, match,
 * and only then split a mixture. Each step states what it is for in one plain
 * sentence, and a step you cannot use yet stays visible but locked rather than
 * disappearing — so the whole path is legible before you start it, and nothing
 * appears out of nowhere half way through.
 */
export type StepState = "locked" | "active" | "done";

export function Step({
  index,
  title,
  hint,
  state,
  children,
}: {
  index: number;
  title: string;
  hint: string;
  state: StepState;
  children?: React.ReactNode;
}) {
  const locked = state === "locked";
  return (
    <Card
      aria-disabled={locked}
      className={cn("gap-3 p-4 transition-opacity", locked && "opacity-55")}
    >
      <div className="flex items-start gap-3">
        <span
          aria-hidden
          className={cn(
            "mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full text-xs font-bold",
            state === "done"
              ? "bg-zone-library text-white"
              : state === "active"
                ? "border-zone-library text-zone-library border-2"
                : "bg-muted text-muted-foreground",
          )}
        >
          {state === "done" ? (
            <Check className="size-3.5" />
          ) : locked ? (
            <Lock className="size-3" />
          ) : (
            index
          )}
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-semibold">
            <span className="sr-only">Step {index}: </span>
            {title}
          </h2>
          <p className="text-muted-foreground text-xs">{hint}</p>
        </div>
      </div>

      {!locked && children ? <div className="pl-9">{children}</div> : null}
    </Card>
  );
}
