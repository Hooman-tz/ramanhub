"use client";

import { useQuery } from "@tanstack/react-query";

import { getFindingOverlay, getSpectrumData } from "@ramanhub/api-client";
import { Skeleton } from "@ramanhub/ui/skeleton";

import { SpectrumChart } from "./charts/spectrum-chart";

const HEIGHT = 140;

/**
 * Feed-card preview strip: the finding's mean-of-members overlay band, only.
 * Per-member traces are never fetched in the feed — that's the detail page's
 * job.
 */
export function FeedCardMedia({ findingId }: { findingId: string }) {
  const overlay = useQuery({
    queryKey: ["overlay", findingId],
    queryFn: () => getFindingOverlay(findingId),
  });

  if (overlay.isLoading) {
    return <Skeleton className="mt-3 w-full" style={{ height: HEIGHT }} />;
  }
  if (overlay.isError || !overlay.data || overlay.data.n < 1) return null;

  return (
    <div className="border-border mt-3 rounded-lg border p-1">
      <SpectrumChart
        mode="band"
        grid={overlay.data.grid_wavenumbers}
        mean={overlay.data.mean}
        std={overlay.data.std}
        height={HEIGHT}
        ariaLabel={`Mean of ${overlay.data.n} member spectra with a ±1 SD band`}
      />
    </div>
  );
}

/**
 * Feed-card preview strip for a standalone spectrum item: a compact single
 * intensity trace. Mirrors `FeedCardMedia` but hits `/spectra/{id}/data`.
 */
export function FeedCardSpectrum({ spectrumId }: { spectrumId: string }) {
  const q = useQuery({
    queryKey: ["spectrum-data", spectrumId],
    queryFn: () => getSpectrumData(spectrumId),
  });

  if (q.isLoading) {
    return <Skeleton className="mt-3 w-full" style={{ height: HEIGHT }} />;
  }
  if (q.isError || !q.data || q.data.wavenumbers.length < 2) return null;

  return (
    <div className="border-border mt-3 rounded-lg border p-1">
      <SpectrumChart
        mode="trace"
        wavenumbers={q.data.wavenumbers}
        intensities={q.data.intensities}
        height={HEIGHT}
        ariaLabel="Raman spectrum preview"
      />
    </div>
  );
}
