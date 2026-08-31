"use client";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";

import type { Pin } from "@ramanhub/api-client";
import { getUserPins, removePin } from "@ramanhub/api-client";
import { Badge } from "@ramanhub/ui/badge";
import { Card } from "@ramanhub/ui/card";

export function PinnedGrid({
  handle,
  isOwner,
}: {
  handle: string;
  isOwner: boolean;
}) {
  const qc = useQueryClient();
  const pins = useQuery({
    queryKey: ["pins", handle],
    queryFn: () => getUserPins(handle),
  });

  const unpin = useMutation({
    mutationFn: (pin: Pin) => removePin(pin.kind, pin.id),
    onSuccess: (list) => qc.setQueryData(["pins", handle], list),
  });

  const items = pins.data ?? [];
  if (items.length === 0) return null;

  return (
    <section>
      <h2 className="text-foreground mb-2 text-base font-semibold tracking-tight">
        Pinned
      </h2>
      <div className="grid gap-3 sm:grid-cols-2">
        {items.slice(0, 4).map((pin) => {
          const body = (
            <Card className="hover:border-primary/40 h-full gap-1.5 p-4 transition-colors motion-reduce:transition-none">
              <div className="flex items-center justify-between gap-2">
                {pin.accession ? (
                  <span className="text-foreground/70 font-mono text-xs">
                    {pin.accession}
                  </span>
                ) : (
                  <span />
                )}
                <Badge variant="outline" className="capitalize">
                  {pin.kind}
                </Badge>
              </div>
              <p className="text-foreground text-sm font-medium">
                {pin.title ?? "Untitled"}
              </p>
            </Card>
          );
          return (
            <div key={`${pin.kind}-${pin.id}`} className="relative">
              {pin.kind === "finding" ? (
                <Link
                  href={`/findings/${pin.id}`}
                  className="focus-visible:ring-ring/50 block rounded-xl focus-visible:ring-[3px] focus-visible:outline-none"
                >
                  {body}
                </Link>
              ) : (
                body
              )}
              {isOwner && (
                <button
                  type="button"
                  aria-label={`Unpin ${pin.title ?? "item"}`}
                  disabled={unpin.isPending}
                  onClick={() => unpin.mutate(pin)}
                  className="bg-background/90 text-foreground/70 hover:text-foreground hover:bg-muted focus-visible:ring-ring/50 absolute top-2 right-2 flex size-8 cursor-pointer items-center justify-center rounded-full border transition-colors focus-visible:ring-[3px] focus-visible:outline-none disabled:opacity-50 motion-reduce:transition-none"
                >
                  <X className="size-4" aria-hidden />
                </button>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
