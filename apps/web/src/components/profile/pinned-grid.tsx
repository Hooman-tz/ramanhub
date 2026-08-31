"use client";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getUserPins, removePin } from "@ramanhub/api-client";
import type { Pin } from "@ramanhub/api-client";

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
      <h2 className="text-muted-foreground mb-2 text-sm font-semibold">
        Pinned
      </h2>
      <div className="grid gap-3 sm:grid-cols-2">
        {items.slice(0, 4).map((pin) => {
          const body = (
            <Card className="h-full gap-1.5 p-4">
              <div className="flex items-center justify-between gap-2">
                {pin.accession ? (
                  <span className="text-muted-foreground font-mono text-xs">
                    {pin.accession}
                  </span>
                ) : (
                  <span />
                )}
                <Badge variant="outline">{pin.kind}</Badge>
              </div>
              <p className="text-sm font-medium">
                {pin.title ?? "Untitled"}
              </p>
            </Card>
          );
          return (
            <div key={`${pin.kind}-${pin.id}`} className="relative">
              {pin.kind === "finding" ? (
                <Link href={`/findings/${pin.id}`} className="block">
                  {body}
                </Link>
              ) : (
                body
              )}
              {isOwner && (
                <button
                  type="button"
                  aria-label="Unpin"
                  disabled={unpin.isPending}
                  onClick={() => unpin.mutate(pin)}
                  className="bg-background/80 text-muted-foreground hover:text-foreground absolute top-2 right-2 rounded-full border px-1.5 text-xs leading-5"
                >
                  ×
                </button>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
