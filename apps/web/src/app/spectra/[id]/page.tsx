import Link from "next/link";
import { notFound } from "next/navigation";
import { BadgeCheck, ExternalLink } from "lucide-react";

import type { Spectrum, SpectrumData } from "@ramanhub/api-client";
import { getSpectrum, getSpectrumData, isApiError } from "@ramanhub/api-client";
import { Badge } from "@ramanhub/ui/badge";
import { Card } from "@ramanhub/ui/card";

import { BackLink } from "~/components/back-link";
import { SpectrumChart } from "~/components/charts/spectrum-chart";
import { serverApiOpts } from "~/lib/server-api";

export const dynamic = "force-dynamic";

/** Any 4xx from the API means "not visible to this viewer" — 404, not 500. */
function notFoundOn4xx(e: unknown): never {
  if (isApiError(e) && e.status >= 400 && e.status < 500) notFound();
  throw e;
}

const asText = (v: unknown) =>
  typeof v === "string" || typeof v === "number" ? String(v) : null;

/** Acquisition rows to try from `confirmed_metadata`; only present ones render. */
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

export default async function SpectrumPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const opts = await serverApiOpts();

  let meta: Spectrum;
  try {
    meta = await getSpectrum(id, opts);
  } catch (e) {
    notFoundOn4xx(e);
  }

  // The chart data is a separate, best-effort fetch. A file with a readable
  // header but no chartable signal (header-only export, unreadable layout,
  // canonicalization failure) makes `/data` fail — the spectrum still exists
  // and its metadata is worth showing, so render the page without the trace
  // rather than 404-ing or crashing. The real error is logged server-side.
  let fetched: SpectrumData | null = null;
  try {
    fetched = await getSpectrumData(id, {}, opts);
  } catch {
    fetched = null;
  }

  const trace = fetched && fetched.wavenumbers.length > 0 ? fetched : null;
  const lo = trace ? Math.round(Math.min(...trace.wavenumbers)) : 0;
  const hi = trace ? Math.round(Math.max(...trace.wavenumbers)) : 0;
  const cm = meta.confirmed_metadata ?? {};
  const laser = asText(cm.laser_wavelength_nm);
  const technique =
    asText(cm.technique) ?? (meta.modality ? meta.modality : null);

  const acqRows = ACQ_ROWS.flatMap(([label, keys, suffix]) => {
    const key = keys.find((k) => asText(cm[k]) != null);
    if (!key) return [];
    const val = asText(cm[key]);
    return [[label, `${val}${suffix ?? ""}`] as const];
  });

  const keyFacts: [string, string][] = [
    ...(trace
      ? ([
          ["Range", `${lo}–${hi} cm⁻¹`],
          [
            "Data points",
            `${trace.wavenumbers.length.toLocaleString()}${
              trace.downsampled
                ? ` of ${trace.total_points.toLocaleString()}`
                : ""
            }`,
          ],
        ] as [string, string][])
      : []),
    ...(laser ? ([["Excitation", `${laser} nm`]] as [string, string][]) : []),
    ...(meta.license_id
      ? ([["License", meta.license_id]] as [string, string][])
      : []),
    ...(meta.published_at
      ? ([
          [
            "Published",
            new Date(meta.published_at).toLocaleDateString(undefined, {
              year: "numeric",
              month: "short",
              day: "numeric",
            }),
          ],
        ] as [string, string][])
      : []),
  ];

  return (
    <main className="mx-auto w-full max-w-4xl px-4 py-8">
      <BackLink />

      {/* Header */}
      <div className="mt-4 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-xl font-bold tracking-tight text-balance">
              {meta.title ?? "Untitled spectrum"}
            </h1>
            {meta.material_type && (
              <span className="text-muted-foreground font-mono text-sm">
                {meta.material_type}
              </span>
            )}
          </div>

          <div className="mt-2 flex flex-wrap items-center gap-2">
            <Badge
              variant={meta.state === "published" ? "secondary" : "outline"}
              className="capitalize"
            >
              {meta.state}
            </Badge>
            {technique && (
              <span className="border-border bg-muted text-muted-foreground rounded-full border px-2 py-0.5 text-xs capitalize">
                {technique}
              </span>
            )}
            {laser && (
              <span className="border-border bg-muted text-muted-foreground rounded-full border px-2 py-0.5 font-mono text-xs">
                {laser} nm
              </span>
            )}
            {meta.doi && (
              <span className="bg-primary/10 text-primary inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium">
                <BadgeCheck className="size-3" aria-hidden />
                DOI linked
              </span>
            )}
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <Link
            href="/lab"
            className="bg-primary text-primary-foreground rounded-lg px-3 py-1.5 text-sm font-medium transition-opacity hover:opacity-90"
          >
            Open in Toolbox
          </Link>
        </div>
      </div>

      {meta.description && (
        <p className="text-foreground/80 mt-3 text-sm leading-relaxed">
          {meta.description}
        </p>
      )}

      {/* Chart */}
      <Card className="mt-6 p-2 sm:p-3">
        {trace ? (
          <SpectrumChart
            mode="trace"
            wavenumbers={trace.wavenumbers}
            intensities={trace.intensities}
            height={340}
            ariaLabel={`Raman spectrum of ${meta.title ?? "sample"}: intensity versus wavenumber`}
          />
        ) : (
          <div className="text-muted-foreground flex h-[340px] flex-col items-center justify-center gap-1 px-4 text-center text-sm">
            <span className="font-medium">Spectrum preview unavailable</span>
            <span className="text-xs">
              We couldn&apos;t read a chartable trace from this file. Its
              metadata is still shown below.
            </span>
          </div>
        )}
      </Card>

      {/* Two-column: facts + sidebar */}
      <div className="mt-6 grid gap-6 md:grid-cols-3">
        <div className="space-y-4 md:col-span-2">
          <h2 className="text-sm font-semibold">Overview</h2>
          <div className="grid grid-cols-2 gap-3">
            {keyFacts.map(([label, value]) => (
              <div
                key={label}
                className="border-border bg-secondary/40 rounded-xl border p-3"
              >
                <div className="text-muted-foreground text-xs">{label}</div>
                <div className="mt-0.5 text-sm font-medium">{value}</div>
              </div>
            ))}
          </div>
        </div>

        <div className="space-y-4">
          {acqRows.length > 0 && (
            <div className="border-border bg-card rounded-xl border p-4">
              <h3 className="text-muted-foreground mb-3 text-xs font-semibold tracking-wider uppercase">
                Acquisition
              </h3>
              <dl className="space-y-2">
                {acqRows.map(([label, value], i) => (
                  <div
                    key={`${label}-${i}`}
                    className="flex justify-between gap-2 text-xs"
                  >
                    <dt className="text-muted-foreground">{label}</dt>
                    <dd className="text-right font-mono">{value}</dd>
                  </div>
                ))}
              </dl>
            </div>
          )}

          {meta.doi && (
            <div className="border-border bg-card rounded-xl border p-4">
              <h3 className="text-muted-foreground mb-2 text-xs font-semibold tracking-wider uppercase">
                DOI
              </h3>
              <a
                href={`https://doi.org/${meta.doi}`}
                target="_blank"
                rel="noopener noreferrer"
                className="text-primary inline-flex items-center gap-1 font-mono text-xs break-all underline underline-offset-2"
              >
                {meta.doi}
                <ExternalLink className="size-3 shrink-0" aria-hidden />
              </a>
            </div>
          )}
        </div>
      </div>

      <p className="text-foreground/50 mt-6 font-mono text-[11px] break-all">
        {id}
      </p>
    </main>
  );
}
