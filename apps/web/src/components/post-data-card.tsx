"use client";

import Link from "next/link";
import { ArrowRight, Database, Maximize2 } from "lucide-react";

import type { Finding } from "@ramanhub/api-client";
import { Badge } from "@ramanhub/ui/badge";
import { Button } from "@ramanhub/ui/button";
import { Card } from "@ramanhub/ui/card";

import { SpectrumExplorer } from "~/components/charts/spectrum-explorer";
import { ForkDataButton } from "~/components/fork-data-button";

/**
 * The data behind a post, and the two things a reader wants to do with it:
 * go to it, or take it.
 *
 * Before this, a post's spectra existed only as chart panels in the gallery —
 * you could see the curve but not the record, and there was no route from
 * "interesting result" to "let me try this myself". Every row here is a real
 * destination, and the dataset header is the canonical home of the data when
 * the author has published one.
 */
export function PostDataCard({
  finding,
  className,
}: {
  finding: Finding;
  className?: string;
}) {
  const members = finding.spectra;
  if (members.length === 0 && !finding.dataset_id) return null;

  const explorerSpectra = members.map((m) => ({
    spectrum_id: m.spectrum_id,
    label: m.label ?? m.title ?? m.accession,
  }));

  // Only a published dataset is a place a reader can actually go; a draft one
  // would 404 for everyone but the author.
  const datasetIsPublic =
    finding.dataset_id && finding.dataset_state === "published";

  return (
    <section className={className ?? "mt-6"} aria-labelledby="post-data-heading">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h2
          id="post-data-heading"
          className="text-muted-foreground text-xs font-semibold tracking-wider uppercase"
        >
          Data
        </h2>
        {members.length > 0 && (
          <SpectrumExplorer
            spectra={explorerSpectra}
            title={finding.title}
            footer={
              <div className="border-border flex justify-end border-t pt-3">
                <ForkDataButton source="finding" id={finding.id} size="sm" />
              </div>
            }
          />
        )}
      </div>

      <Card className="gap-0 overflow-hidden p-0">
        {finding.dataset_id && (
          <div className="bg-card border-b px-3 py-2.5">
            {datasetIsPublic ? (
              <Link
                href={`/datasets/${finding.dataset_id}`}
                className="group focus-visible:ring-ring/50 flex items-center gap-2 rounded focus-visible:ring-[3px] focus-visible:outline-none"
              >
                <Database
                  className="text-muted-foreground size-4 shrink-0"
                  aria-hidden
                />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium">
                    {finding.dataset_name ?? "Dataset"}
                  </span>
                  <span className="text-muted-foreground font-mono text-xs">
                    {finding.dataset_accession}
                  </span>
                </span>
                <ArrowRight
                  className="text-muted-foreground group-hover:text-foreground size-4 shrink-0 transition-colors motion-reduce:transition-none"
                  aria-hidden
                />
              </Link>
            ) : (
              <div className="flex items-center gap-2">
                <Database
                  className="text-muted-foreground size-4 shrink-0"
                  aria-hidden
                />
                <span className="min-w-0 flex-1 truncate text-sm font-medium">
                  {finding.dataset_name ?? "Dataset"}
                </span>
                <Badge variant="secondary" className="shrink-0 text-xs">
                  unpublished
                </Badge>
              </div>
            )}
          </div>
        )}

        <ul className="divide-border divide-y">
          {members.map((m) => (
            <li
              key={m.spectrum_id}
              className="flex items-center gap-2 px-3 py-2"
            >
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm">
                  {m.label ?? m.title ?? "Untitled spectrum"}
                </span>
                <span className="text-muted-foreground font-mono text-xs">
                  {m.accession ?? m.spectrum_id.slice(0, 8)}
                  <span className="ml-1.5 font-sans">· {m.state}</span>
                </span>
              </span>

              <SpectrumExplorer
                spectra={[
                  {
                    spectrum_id: m.spectrum_id,
                    label: m.label ?? m.title ?? m.accession,
                  },
                ]}
                title={m.label ?? m.title ?? "Spectrum"}
                trigger={
                  <Button
                    variant="ghost"
                    size="icon"
                    className="size-9 shrink-0 cursor-pointer"
                    aria-label={`Explore ${m.label ?? m.title ?? "this spectrum"}`}
                  >
                    <Maximize2 className="size-4" aria-hidden />
                  </Button>
                }
              />

              <Link
                href={`/spectra/${m.spectrum_id}`}
                aria-label={`Open ${m.label ?? m.title ?? "this spectrum"}`}
                className="text-muted-foreground hover:text-foreground focus-visible:ring-ring/50 flex size-9 shrink-0 items-center justify-center rounded-md transition-colors focus-visible:ring-[3px] focus-visible:outline-none motion-reduce:transition-none"
              >
                <ArrowRight className="size-4" aria-hidden />
              </Link>
            </li>
          ))}
        </ul>
      </Card>
    </section>
  );
}
