"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useMutation } from "@tanstack/react-query";
import { ScanSearch } from "lucide-react";

import type { Spectrum } from "@ramanhub/api-client";
import { matchAgainstLibrary, unmixAgainstLibrary } from "@ramanhub/api-client";
import { detectPeaks } from "@ramanhub/processing";
import { cn } from "@ramanhub/ui";
import { Button } from "@ramanhub/ui/button";
import { Card } from "@ramanhub/ui/card";
import { Skeleton } from "@ramanhub/ui/skeleton";

import type { SpectrumBuffer } from "~/lib/spectra-buffer";
import { SpectrumChart } from "~/components/charts/spectrum-chart";
import { VIEWER_HEIGHT } from "~/components/lab/viewer";
import {
  ComponentChooser,
  MatchList,
  MixtureNotice,
  UnmixReadout,
} from "~/components/library/pieces";
import { useSpectrumBuffer } from "~/lib/spectra-buffer";

/**
 * The Data Lab's Library tab: identify whatever the workbench has selected.
 *
 * Deliberately the short version. It assumes you already have a spectrum in
 * hand, so it skips straight to matching — no numbered steps, no picker. The
 * guided walk-through, for when you are starting from nothing, is the
 * standalone `/library` page.
 *
 * Both render the same result components from `~/components/library/pieces`.
 * That sharing is not just tidiness: these components make claims about a
 * user's data — a similarity percentage, a composition — and two drifting
 * copies would eventually disagree about how confident to look.
 */
export function LibraryPanel({
  spectrumId,
  spectrum,
  buffer,
  bufferLoading,
}: {
  spectrumId: string | null;
  spectrum: Spectrum | undefined;
  buffer: SpectrumBuffer | undefined;
  bufferLoading: boolean;
}) {
  const [picked, setPicked] = useState<string[]>([]);
  const [overlaid, setOverlaid] = useState<string | null>(null);

  const match = useMutation({
    mutationFn: (id: string) =>
      matchAgainstLibrary({ spectrum_id: id, top_k: 12 }),
    onSuccess: (result) => {
      setPicked(result.suggested_component_reference_ids.slice(0, 3));
      setOverlaid(result.matches[0]?.reference.id ?? null);
    },
  });

  const unmix = useMutation({
    mutationFn: (ids: string[]) => {
      if (!spectrumId) throw new Error("No spectrum selected.");
      return unmixAgainstLibrary({ spectrum_id: spectrumId, reference_ids: ids });
    },
  });

  const result = match.data;

  const localPeaks = useMemo(() => {
    if (!buffer) return null;
    try {
      return detectPeaks(buffer);
    } catch {
      return null;
    }
  }, [buffer]);

  // Server peaks once we have them, local ones before — never both at once, as
  // two slightly-offset marker sets read worse than either alone.
  const markers = useMemo(() => {
    const source = result
      ? result.query_peaks.map((p) => ({ cm1: p.cm1, rel: p.rel_height }))
      : (localPeaks?.peaks ?? []).map((p) => ({ cm1: p.cm1, rel: p.relHeight }));
    return source.map((p) => ({
      cm1: p.cm1,
      label: p.rel >= 0.5 ? `${Math.round(p.cm1)}` : undefined,
    }));
  }, [result, localPeaks]);

  const overlayRef = result?.matches.find((m) => m.reference.id === overlaid);
  const overlayBuffer = useSpectrumBuffer(
    overlayRef?.reference.spectrum_id ?? null,
  );

  const series = useMemo(() => {
    if (!buffer) return [];
    const out = [
      {
        name: "Yours",
        wavenumbers: Array.from(buffer.wavenumbers),
        intensities: Array.from(buffer.intensities),
      },
    ];
    if (overlayBuffer.data && overlayRef) {
      out.push({
        name: overlayRef.reference.compound_name,
        wavenumbers: Array.from(overlayBuffer.data.wavenumbers),
        intensities: Array.from(overlayBuffer.data.intensities),
      });
    }
    return out;
  }, [buffer, overlayBuffer.data, overlayRef]);

  const togglePick = (id: string) =>
    setPicked((prev) =>
      prev.includes(id)
        ? prev.filter((p) => p !== id)
        : prev.length >= 6
          ? prev
          : [...prev, id],
    );

  if (!spectrumId) {
    return (
      <Card className="p-4">
        <div
          className={cn(
            "flex flex-col items-center justify-center gap-3 text-center",
            VIEWER_HEIGHT,
          )}
        >
          <ScanSearch className="text-muted-foreground size-8" aria-hidden />
          <p className="text-muted-foreground max-w-sm text-sm">
            Select a spectrum on the left to identify it against the reference
            library.
          </p>
          <Button variant="outline" size="sm" asChild>
            <Link href="/library">Or browse the library</Link>
          </Button>
        </div>
      </Card>
    );
  }

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <Card className="gap-3 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="min-w-0">
            <h3 className="truncate text-sm font-medium">
              {spectrum?.title ?? "Selected spectrum"}
            </h3>
            <p className="text-muted-foreground text-xs">
              {result
                ? `${result.query_peaks.length} bands`
                : localPeaks
                  ? `${localPeaks.peaks.length} bands · estimated on this machine`
                  : ""}
            </p>
          </div>
          <Button
            size="sm"
            disabled={match.isPending || !buffer}
            onClick={() => match.mutate(spectrumId)}
          >
            {match.isPending ? "Searching…" : "Find matches"}
          </Button>
        </div>

        {bufferLoading ? (
          <Skeleton className={VIEWER_HEIGHT} />
        ) : !buffer ? (
          <p className="text-muted-foreground text-sm">
            This spectrum&rsquo;s data could not be loaded.
          </p>
        ) : (
          <div className={cn("rounded-lg border p-2", VIEWER_HEIGHT)}>
            <SpectrumChart
              mode="trace"
              height="100%"
              markers={markers}
              series={series}
              display={{ normalize: "max", showLegend: series.length > 1 }}
              ariaLabel="Selected spectrum with its detected bands"
            />
          </div>
        )}
      </Card>

      {match.error && (
        <Card className="border-destructive/40 p-4">
          <p className="text-destructive text-sm">
            {match.error.message}
          </p>
        </Card>
      )}

      {result && (
        <Card className="gap-3 p-4">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="text-sm font-medium">Closest references</h3>
            <p className="text-muted-foreground text-xs">
              {result.candidates_screened} candidate
              {result.candidates_screened === 1 ? "" : "s"} checked
            </p>
          </div>

          {result.matches.length === 0 ? (
            <p className="text-muted-foreground text-sm">
              Nothing in the library resembles this spectrum yet.
            </p>
          ) : (
            <MatchList
              result={result}
              overlaid={overlaid}
              onOverlay={setOverlaid}
              picked={picked}
              onTogglePick={togglePick}
              showPicker={false}
            />
          )}
        </Card>
      )}

      {result && result.matches.length > 0 && (
        <Card className="gap-3 p-4">
          <h3 className="text-sm font-medium">Split a mixture</h3>
          {result.mixture_suspected ? (
            <MixtureNotice result={result} />
          ) : (
            <p className="text-muted-foreground text-xs">
              The top match explains this spectrum on its own, so this is
              optional.
            </p>
          )}

          <ComponentChooser
            result={result}
            picked={picked}
            onToggle={togglePick}
          />

          <div className="flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              disabled={picked.length < 2 || unmix.isPending}
              onClick={() => unmix.mutate(picked)}
            >
              {unmix.isPending
                ? "Fitting…"
                : `Split into ${Math.max(picked.length, 2)} components`}
            </Button>
            {picked.length < 2 && (
              <span className="text-muted-foreground text-xs">
                Choose at least two compounds to split between.
              </span>
            )}
          </div>

          {unmix.error && (
            <p className="text-destructive text-sm">
              {unmix.error.message}
            </p>
          )}

          {unmix.data && <UnmixReadout result={unmix.data} />}
        </Card>
      )}
    </div>
  );
}
