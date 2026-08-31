import { notFound } from "next/navigation";
import { ExternalLink } from "lucide-react";

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

export default async function SpectrumPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const opts = await serverApiOpts();

  let meta: Spectrum;
  let data: SpectrumData;
  try {
    [meta, data] = await Promise.all([
      getSpectrum(id, opts),
      getSpectrumData(id, {}, opts),
    ]);
  } catch (e) {
    notFoundOn4xx(e);
  }

  if (!data.wavenumbers.length) notFound();

  const lo = Math.round(Math.min(...data.wavenumbers));
  const hi = Math.round(Math.max(...data.wavenumbers));
  const cm = meta.confirmed_metadata ?? {};
  const asText = (v: unknown) =>
    typeof v === "string" || typeof v === "number" ? String(v) : null;
  const laser = asText(cm.laser_wavelength_nm);
  const instrument = [asText(cm.instrument_vendor), asText(cm.instrument_model)]
    .filter(Boolean)
    .join(" ");

  return (
    <main className="mx-auto w-full max-w-2xl px-4 py-8">
      <BackLink />

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <Badge variant={meta.state === "published" ? "secondary" : "outline"}>
          {meta.state}
        </Badge>
        <span className="text-foreground/70 text-xs capitalize">
          {meta.modality} spectrum
        </span>
        {meta.material_type ? (
          <span className="text-foreground/70 text-xs">
            · {meta.material_type}
          </span>
        ) : null}
      </div>

      <h1 className="mt-2 text-2xl font-bold tracking-tight text-balance">
        {meta.title ?? "Untitled spectrum"}
      </h1>

      {meta.description ? (
        <p className="text-foreground/80 mt-2 text-sm leading-relaxed">
          {meta.description}
        </p>
      ) : null}

      <dl className="text-foreground/80 mt-4 flex flex-wrap gap-x-5 gap-y-1 text-xs">
        <div className="inline-flex gap-1">
          <dt className="text-foreground/60">Range</dt>
          <dd>
            {lo}–{hi} cm⁻¹
          </dd>
        </div>
        <div className="inline-flex gap-1">
          <dt className="text-foreground/60">Points</dt>
          <dd>
            {data.wavenumbers.length.toLocaleString()}
            {data.downsampled
              ? ` (of ${data.total_points.toLocaleString()})`
              : ""}
          </dd>
        </div>
        {laser ? (
          <div className="inline-flex gap-1">
            <dt className="text-foreground/60">Laser</dt>
            <dd>{laser} nm</dd>
          </div>
        ) : null}
        {instrument ? (
          <div className="inline-flex gap-1">
            <dt className="text-foreground/60">Instrument</dt>
            <dd>{instrument}</dd>
          </div>
        ) : null}
        {meta.doi ? (
          <a
            href={`https://doi.org/${meta.doi}`}
            className="text-primary focus-visible:ring-ring/50 inline-flex items-center gap-1 rounded underline underline-offset-2 focus-visible:ring-[3px] focus-visible:outline-none"
          >
            {meta.doi}
            <ExternalLink className="size-3" aria-hidden />
          </a>
        ) : null}
      </dl>

      <Card className="mt-6 p-2 sm:p-3">
        <SpectrumChart
          mode="trace"
          wavenumbers={data.wavenumbers}
          intensities={data.intensities}
          height={340}
          ariaLabel={`Raman spectrum of ${meta.title ?? "sample"}: intensity versus wavenumber`}
        />
      </Card>

      <p className="text-foreground/50 mt-3 font-mono text-[11px] break-all">
        {id}
      </p>
    </main>
  );
}
