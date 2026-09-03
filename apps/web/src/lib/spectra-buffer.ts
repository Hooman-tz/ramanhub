"use client";

import { useEffect, useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import type { BufferedSpectrum } from "@ramanhub/processing";
import { getAlgorithmCatalog, getSpectrumData } from "@ramanhub/api-client";
import { toBuffer } from "@ramanhub/processing";

/**
 * The client-side working set.
 *
 * The lab used to fetch a spectrum's arrays once per view change and once more
 * after every Apply. That made the network part of the interaction loop. Here
 * a spectrum's **raw** arrays are fetched exactly once, converted to
 * `Float64Array` once, and then held in memory for the rest of the session —
 * `@ramanhub/processing` recomputes any pipeline against that buffer locally,
 * so tuning never touches the network at all.
 *
 * The buffer holds raw arrays only. Processed curves are derived, never
 * cached: deriving one is a couple of milliseconds, whereas caching it would
 * mean holding a copy per parameter combination the user tried.
 *
 * Server-side records are untouched by any of this. Committing a pipeline
 * still goes through `POST /raw-files/{id}/ledgers`, which is what actually
 * creates the ledger and its stored `.npz`.
 */

/**
 * Point budget per buffered spectrum. Matches what the chart can resolve; the
 * server downsamples above it and reports `total_points` so the UI can say so.
 */
export const BUFFER_MAX_POINTS = 4000;

/** How long an untouched buffer survives before React Query evicts it. */
const BUFFER_GC_MS = 30 * 60 * 1000;

/** Spectra warmed at once when a dataset is opened. Keeps a big folder from
 * opening dozens of parallel requests at a 1 GB-RAM backend. */
const WARM_CONCURRENCY = 3;

export interface SpectrumBuffer extends BufferedSpectrum {
  /** True when the server reduced the point count to fit `BUFFER_MAX_POINTS`. */
  downsampled: boolean;
  /** Points in the stored file, before any downsampling. */
  totalPoints: number;
}

const bufferKey = (id: string) => ["raw-buffer", id] as const;

async function fetchBuffer(id: string): Promise<SpectrumBuffer> {
  const data = await getSpectrumData(id, {
    raw: true,
    maxPoints: BUFFER_MAX_POINTS,
  });
  return {
    ...toBuffer(data.wavenumbers, data.intensities),
    downsampled: data.downsampled,
    totalPoints: data.total_points,
  };
}

/**
 * Raw arrays for one spectrum, fetched once and then resident.
 *
 * `staleTime: Infinity` is correct rather than merely convenient: a raw file
 * is immutable by design, so there is no version of it to refetch.
 */
export function useSpectrumBuffer(spectrumId: string | null) {
  return useQuery({
    queryKey: bufferKey(spectrumId ?? ""),
    queryFn: () => {
      if (!spectrumId) throw new Error("No spectrum selected.");
      return fetchBuffer(spectrumId);
    },
    enabled: !!spectrumId,
    staleTime: Infinity,
    gcTime: BUFFER_GC_MS,
  });
}

/**
 * Warm the buffer for every spectrum in the open dataset, a few at a time, so
 * switching between them is instant.
 *
 * Prefetches are best-effort: one spectrum the viewer can't read (or a request
 * that loses a race with unmount) must not disturb the one they actually
 * selected, so failures are swallowed here and surfaced by `useSpectrumBuffer`
 * if and when that spectrum is opened.
 */
export function useWarmDatasetBuffers(spectrumIds: readonly string[]): void {
  const qc = useQueryClient();
  // Effects compare deps by identity; a fresh array every render would restart
  // the warm-up on every keystroke elsewhere in the page.
  const idKey = spectrumIds.join(",");

  useEffect(() => {
    const ids = idKey ? idKey.split(",") : [];
    if (ids.length === 0) return;

    let cancelled = false;

    const warm = async () => {
      for (let i = 0; i < ids.length; i += WARM_CONCURRENCY) {
        if (cancelled) return;
        await Promise.all(
          ids.slice(i, i + WARM_CONCURRENCY).map((id) =>
            qc
              .prefetchQuery({
                queryKey: bufferKey(id),
                queryFn: () => fetchBuffer(id),
                staleTime: Infinity,
                gcTime: BUFFER_GC_MS,
              })
              .catch(() => undefined),
          ),
        );
      }
    };

    void warm();
    return () => {
      cancelled = true;
    };
  }, [idKey, qc]);
}

/**
 * `step_type -> version` from the live algorithm catalog.
 *
 * Passed to `previewPipeline` so a local port that has fallen behind the
 * server is reported as "preview unavailable" rather than silently drawing a
 * curve that Apply would not reproduce.
 */
export function useAlgorithmVersions(): Record<string, string> | undefined {
  const catalog = useQuery({
    queryKey: ["algorithms"],
    queryFn: () => getAlgorithmCatalog(),
    staleTime: 60 * 60 * 1000,
  });

  return useMemo(() => {
    if (!catalog.data) return undefined;
    return Object.fromEntries(
      catalog.data.algorithms.map((a) => [a.step_type, a.version]),
    );
  }, [catalog.data]);
}
