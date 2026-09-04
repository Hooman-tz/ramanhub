"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ChevronRight, GitFork, Lock } from "lucide-react";

import { getSpectrumLineage } from "@ramanhub/api-client";

/**
 * Where this data came from — the breadcrumb back to the original.
 *
 * `parent_spectrum_id` is written only by the fork path, so a non-empty chain
 * means "this is a working copy of someone else's data". Without this, a
 * forked spectrum is indistinguishable from an original, and a reader has no
 * way to find (or cite) the record it was copied from.
 *
 * Renders nothing when there is no lineage, which is the common case — an
 * original post should not carry an empty breadcrumb bar.
 */
export function ProvenanceTrail({
  spectrumId,
  className,
}: {
  spectrumId: string;
  className?: string;
}) {
  const lineage = useQuery({
    queryKey: ["spectrum-lineage", spectrumId],
    queryFn: () => getSpectrumLineage(spectrumId),
    // Lineage only changes when someone forks; no need to refetch on focus.
    staleTime: 5 * 60_000,
  });

  const ancestors = lineage.data?.ancestors ?? [];
  if (ancestors.length === 0) return null;

  return (
    <nav
      aria-label="Data provenance"
      className={
        className ??
        "border-border bg-secondary/40 mt-3 flex flex-wrap items-center gap-x-1.5 gap-y-1 rounded-lg border px-2.5 py-1.5 text-xs"
      }
    >
      <GitFork className="text-muted-foreground size-3.5 shrink-0" aria-hidden />
      <span className="text-muted-foreground">Forked from</span>
      <ol className="flex flex-wrap items-center gap-x-1 gap-y-1">
        {lineage.data?.truncated && (
          <li className="text-muted-foreground" aria-label="Earlier ancestors">
            …
            <ChevronRight
              className="mx-0.5 inline size-3 align-[-1px]"
              aria-hidden
            />
          </li>
        )}
        {ancestors.map((node, i) => (
          <li key={node.id ?? `redacted-${i}`} className="flex items-center">
            {node.redacted ? (
              // The source was public when it was forked but has since been
              // pulled back. The link stays in the chain (the depth is real
              // information) without leaking who or what it was.
              <span
                className="text-muted-foreground inline-flex items-center gap-1"
                title="This record is no longer public"
              >
                <Lock className="size-3" aria-hidden />
                private record
              </span>
            ) : (
              <Link
                href={`/spectra/${node.id}`}
                className="text-primary hover:underline"
              >
                <span className="font-mono">
                  {node.accession ?? node.title ?? "spectrum"}
                </span>
                {node.owner_handle && (
                  <span className="text-muted-foreground">
                    {" "}
                    · @{node.owner_handle}
                  </span>
                )}
              </Link>
            )}
            {i < ancestors.length - 1 && (
              <ChevronRight
                className="text-muted-foreground mx-0.5 size-3"
                aria-hidden
              />
            )}
          </li>
        ))}
      </ol>
    </nav>
  );
}
