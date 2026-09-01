"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import type { LibrarySpectrum } from "@ramanhub/api-client";
import { getMyLibrary } from "@ramanhub/api-client";
import { cn } from "@ramanhub/ui";
import { Card } from "@ramanhub/ui/card";
import { Skeleton } from "@ramanhub/ui/skeleton";

/** Maps a library spectrum's state fields to a status dot + short step label. */
function status(s: LibrarySpectrum): { dot: string; label: string } {
  if (s.state === "published")
    return { dot: "bg-success", label: "Published to commons" };
  if (s.qc_state === "running" || s.qc_state === "queued")
    return { dot: "bg-chart-2 animate-pulse", label: "QC in progress" };
  if (s.metadata_state !== "confirmed")
    return { dot: "bg-accent", label: "Awaiting metadata review" };
  if (s.publish_ready) return { dot: "bg-primary", label: "Ready to publish" };
  return { dot: "bg-muted-foreground/50", label: "Draft" };
}

export function SpectrumProjects() {
  const lib = useQuery({
    queryKey: ["my-library", "recent"],
    queryFn: () => getMyLibrary({ limit: 8 }),
  });
  const rows = lib.data ?? [];

  return (
    <Card className="gap-0 overflow-hidden py-0">
      <div className="border-border flex items-center justify-between border-b px-5 py-3.5">
        <div className="text-sm font-semibold">Spectrum projects</div>
        <Link
          href="/lab"
          className="text-primary text-[11px] font-medium hover:underline"
        >
          View all in My Lab →
        </Link>
      </div>

      {lib.isLoading ? (
        <div className="space-y-2 p-4">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </div>
      ) : lib.isError ? (
        <p className="text-muted-foreground p-5 text-sm">
          Could not load your spectra.
        </p>
      ) : rows.length === 0 ? (
        <p className="text-muted-foreground p-5 text-sm">
          No spectra yet.{" "}
          <Link href="/upload" className="text-primary hover:underline">
            Upload one
          </Link>
          .
        </p>
      ) : (
        <div className="divide-border divide-y">
          {rows.map((s) => {
            const st = status(s);
            return (
              <div
                key={s.id}
                className="hover:bg-secondary/30 flex items-center gap-3 px-5 py-3 transition-colors"
              >
                <span className={cn("size-2 shrink-0 rounded-full", st.dot)} />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium">
                    {s.title ?? "Untitled spectrum"}
                  </div>
                  <div className="text-muted-foreground mt-0.5 text-[10px]">
                    {st.label}
                    {s.material_type ? ` · ${s.material_type}` : ""}
                  </div>
                </div>
                <Link
                  href={`/spectra/${s.id}`}
                  className="text-muted-foreground hover:text-primary shrink-0 text-[11px] font-medium transition-colors"
                >
                  Open
                </Link>
              </div>
            );
          })}
        </div>
      )}
    </Card>
  );
}
