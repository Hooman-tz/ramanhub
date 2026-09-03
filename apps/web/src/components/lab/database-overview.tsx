"use client";

import { useMemo } from "react";
import Link from "next/link";
import { Boxes, ExternalLink } from "lucide-react";

import type { Dataset, LibrarySpectrum, Spectrum } from "@ramanhub/api-client";
import { Badge } from "@ramanhub/ui/badge";
import { Card } from "@ramanhub/ui/card";
import { Skeleton } from "@ramanhub/ui/skeleton";

import type { SpectrumBuffer } from "~/lib/spectra-buffer";
import { SpectrumChart } from "~/components/charts/spectrum-chart";

/**
 * The Data Lab's database view: what a record *is*, as stored.
 *
 * Always draws the raw trace, never a preview of a staged pipeline — this is
 * the view for checking what was actually measured and filed. Processing lives
 * in Prep, one tab over, so the two can't be confused with each other.
 */

const asText = (v: unknown) =>
  typeof v === "string" || typeof v === "number" ? String(v) : null;

/** Acquisition rows worth showing, when `confirmed_metadata` has them. */
const ACQ_ROWS: [label: string, keys: string[], suffix?: string][] = [
  ["Instrument", ["instrument_model", "instrument_vendor"]],
  ["Laser", ["laser_wavelength_nm"], " nm"],
  ["Power", ["laser_power_mw"], " mW"],
  ["Integration", ["integration_time_s"], " s"],
  ["Integration", ["integration_time_ms"], " ms"],
  ["Objective", ["objective"]],
  ["Grating", ["grating_lines_per_mm"], " gr/mm"],
  ["Accumulations", ["accumulations"]],
];

function DatasetSummary({
  dataset,
  loadedCount,
}: {
  dataset: Dataset;
  loadedCount: number;
}) {
  return (
    <Card className="gap-2 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <Boxes className="text-muted-foreground size-4" aria-hidden />
        <h2 className="text-sm font-semibold">{dataset.name}</h2>
        <Badge variant="outline" className="text-[0.7rem] font-normal">
          {dataset.modality}
        </Badge>
        <span className="text-muted-foreground text-xs">
          {dataset.spectra.length}{" "}
          {dataset.spectra.length === 1 ? "spectrum" : "spectra"}
          {loadedCount < dataset.spectra.length &&
            ` · ${loadedCount} loaded so far`}
        </span>
      </div>
      {dataset.description && (
        <p className="text-foreground/80 text-sm leading-relaxed">
          {dataset.description}
        </p>
      )}
    </Card>
  );
}

export function DatabaseOverview({
  row,
  spectrum,
  buffer,
  bufferLoading,
  dataset,
  datasets,
  loadedCount,
}: {
  /** The library record for the selected spectrum, if it is loaded. */
  row: LibrarySpectrum | undefined;
  /** The fuller record from `GET /spectra/{id}`. */
  spectrum: Spectrum | undefined;
  buffer: SpectrumBuffer | undefined;
  bufferLoading: boolean;
  /** The dataset currently scoping the list, if any. */
  dataset: Dataset | undefined;
  datasets: Dataset[];
  /** How many of `dataset.spectra` are paged in and therefore listed. */
  loadedCount: number;
}) {
  const trace = useMemo(() => {
    if (!buffer) return null;
    return {
      wavenumbers: Array.from(buffer.wavenumbers),
      intensities: Array.from(buffer.intensities),
    };
  }, [buffer]);

  const cm = spectrum?.confirmed_metadata ?? {};
  const acqRows = ACQ_ROWS.flatMap(([label, keys, suffix]) => {
    const key = keys.find((k) => asText(cm[k]) != null);
    if (!key) return [];
    return [[label, `${asText(cm[key])}${suffix ?? ""}`] as const];
  });

  // Every folder this spectrum belongs to — the membership view the list
  // itself can't show, since the list is scoped to one dataset at a time.
  const memberOf = row
    ? datasets.filter((d) => d.spectra.some((s) => s.id === row.id))
    : [];

  return (
    <div className="flex flex-col gap-3">
      {dataset && (
        <DatasetSummary dataset={dataset} loadedCount={loadedCount} />
      )}

      {!row ? (
        <Card className="text-muted-foreground flex h-[320px] flex-col items-center justify-center gap-1 p-6 text-center text-sm">
          <span className="font-medium">No spectrum selected</span>
          <span className="text-xs">
            Pick one from the list to see what was measured and filed.
          </span>
        </Card>
      ) : (
        <>
          <Card className="min-w-0 gap-3 p-3">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div className="min-w-0">
                <h2 className="truncate text-sm font-semibold">
                  {spectrum?.title ?? row.title ?? "Untitled spectrum"}
                </h2>
                <div className="mt-1 flex flex-wrap items-center gap-1.5">
                  <Badge
                    variant={
                      row.state === "published" ? "secondary" : "outline"
                    }
                    className="capitalize"
                  >
                    {row.state}
                  </Badge>
                  {row.material_type && (
                    <Badge
                      variant="outline"
                      className="text-[0.7rem] font-normal"
                    >
                      {row.material_type}
                    </Badge>
                  )}
                  {row.excitation_wavelength_nm != null && (
                    <span className="text-muted-foreground font-mono text-xs">
                      {row.excitation_wavelength_nm} nm
                    </span>
                  )}
                </div>
              </div>
              <Link
                href={`/spectra/${row.id}`}
                className="text-muted-foreground hover:text-primary inline-flex shrink-0 items-center gap-1 text-xs font-medium"
              >
                Public page
                <ExternalLink className="size-3" aria-hidden />
              </Link>
            </div>

            {spectrum?.description && (
              <p className="text-foreground/80 text-sm leading-relaxed">
                {spectrum.description}
              </p>
            )}

            <div className="rounded-lg border p-2">
              {bufferLoading && !trace ? (
                <Skeleton className="h-[300px] w-full" />
              ) : trace ? (
                <SpectrumChart
                  mode="trace"
                  wavenumbers={trace.wavenumbers}
                  intensities={trace.intensities}
                  height={300}
                  ariaLabel="Raw spectrum trace as stored"
                />
              ) : (
                <p className="text-muted-foreground p-4 text-center text-sm">
                  No chartable trace could be read from this file.
                </p>
              )}
            </div>

            {buffer && (
              <p className="text-muted-foreground text-xs">
                Raw · {buffer.wavenumbers.length.toLocaleString()} of{" "}
                {buffer.totalPoints.toLocaleString()} points
                {buffer.downsampled ? " · downsampled for display" : ""}
              </p>
            )}
          </Card>

          <div className="grid gap-3 md:grid-cols-2">
            <Card className="gap-3 p-4">
              <h3 className="text-muted-foreground text-xs font-semibold tracking-wider uppercase">
                Record
              </h3>
              <dl className="space-y-2 text-xs">
                {(
                  [
                    ["Modality", row.modality],
                    ["Metadata", row.metadata_state],
                    ["QC", row.qc_state],
                    [
                      "SNR",
                      row.snr != null ? String(Math.round(row.snr)) : "—",
                    ],
                    ["DOI", row.doi ?? "—"],
                    [
                      "Added",
                      new Date(row.created_at).toLocaleDateString(undefined, {
                        year: "numeric",
                        month: "short",
                        day: "numeric",
                      }),
                    ],
                  ] as [string, string][]
                ).map(([label, value]) => (
                  <div key={label} className="flex justify-between gap-2">
                    <dt className="text-muted-foreground">{label}</dt>
                    <dd className="text-right font-mono break-all">{value}</dd>
                  </div>
                ))}
              </dl>
            </Card>

            <Card className="gap-3 p-4">
              <h3 className="text-muted-foreground text-xs font-semibold tracking-wider uppercase">
                Acquisition
              </h3>
              {acqRows.length > 0 ? (
                <dl className="space-y-2 text-xs">
                  {acqRows.map(([label, value], i) => (
                    <div
                      key={`${label}-${i}`}
                      className="flex justify-between gap-2"
                    >
                      <dt className="text-muted-foreground">{label}</dt>
                      <dd className="text-right font-mono">{value}</dd>
                    </div>
                  ))}
                </dl>
              ) : (
                <p className="text-muted-foreground text-xs">
                  No acquisition metadata was recorded for this file.
                </p>
              )}

              <h3 className="text-muted-foreground mt-2 text-xs font-semibold tracking-wider uppercase">
                Datasets
              </h3>
              {memberOf.length > 0 ? (
                <div className="flex flex-wrap gap-1.5">
                  {memberOf.map((d) => (
                    <Badge
                      key={d.id}
                      variant="outline"
                      className="text-[0.7rem] font-normal"
                    >
                      {d.name}
                    </Badge>
                  ))}
                </div>
              ) : (
                <p className="text-muted-foreground text-xs">
                  Not in any dataset yet — add it from the row menu.
                </p>
              )}
            </Card>
          </div>
        </>
      )}
    </div>
  );
}
