"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Bookmark } from "lucide-react";

import { getUserPins } from "@ramanhub/api-client";
import { Card } from "@ramanhub/ui/card";
import { Skeleton } from "@ramanhub/ui/skeleton";

/** The requester's pinned spectra / findings — the "saved posts" shelf. */
export function SavedPosts({ handle }: { handle: string }) {
  const pins = useQuery({
    queryKey: ["pins", handle],
    queryFn: () => getUserPins(handle),
  });
  const rows = pins.data ?? [];

  return (
    <Card className="gap-0 overflow-hidden py-0">
      <div className="border-border flex items-center justify-between border-b px-5 py-3.5">
        <div className="text-sm font-semibold">Pinned</div>
        {rows.length > 0 && (
          <span className="text-muted-foreground text-[10px]">
            {rows.length} pinned
          </span>
        )}
      </div>

      {pins.isLoading ? (
        <div className="space-y-2 p-4">
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-8 w-full" />
        </div>
      ) : rows.length === 0 ? (
        <p className="text-muted-foreground p-5 text-center text-xs">
          Items you pin from a spectrum or finding show up here.
        </p>
      ) : (
        <div className="divide-border divide-y">
          {rows.map((p) => (
            <Link
              key={`${p.kind}-${p.id}`}
              href={
                p.kind === "finding" ? `/findings/${p.id}` : `/spectra/${p.id}`
              }
              className="group hover:bg-secondary/30 flex items-start gap-3 px-5 py-3 transition-colors"
            >
              <Bookmark
                className="text-primary mt-0.5 size-3.5 shrink-0"
                aria-hidden
              />
              <div className="min-w-0 flex-1">
                <div className="group-hover:text-primary text-xs leading-snug font-medium transition-colors">
                  {p.title ?? "Untitled"}
                </div>
                <div className="text-muted-foreground mt-0.5 flex items-center gap-1.5 text-[10px]">
                  <span className="uppercase">{p.kind}</span>
                  {p.accession && (
                    <>
                      <span aria-hidden>·</span>
                      <span className="font-mono">{p.accession}</span>
                    </>
                  )}
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}
    </Card>
  );
}
