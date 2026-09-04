"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Library, Search } from "lucide-react";

import { getSpectrum, matchAgainstLibrary, searchReferences, unmixAgainstLibrary } from "@ramanhub/api-client";
import { detectPeaks } from "@ramanhub/processing";
import { cn } from "@ramanhub/ui";
import { Button } from "@ramanhub/ui/button";
import { Card } from "@ramanhub/ui/card";
import { Input } from "@ramanhub/ui/input";
import { Skeleton } from "@ramanhub/ui/skeleton";

import { SpectrumChart } from "~/components/charts/spectrum-chart";
import {
  ComponentChooser,
  EmptyCard,
  MatchList,
  MixtureNotice,
  ReferenceRow,
  UnmixReadout,
} from "~/components/library/pieces";
import { Step } from "~/components/library/step";
import { SpectrumPickerDialog } from "~/components/spectrum-picker";
import { useSpectrumBuffer } from "~/lib/spectra-buffer";

/**
 * The standalone Library: identify one spectrum, start to finish.
 *
 * Distinct from the Data Lab's Library tab, which acts on whatever the lab
 * workbench already has selected. Here nothing is assumed — choosing the
 * spectrum is step one — so the page works as an errand of its own rather than
 * as the tail of a lab session.
 */
export function IdentifyFlow({ isFullUser }: { isFullUser: boolean }) {
  const [task, setTask] = useState<"identify" | "browse">("identify");
  const [spectrumId, setSpectrumId] = useState<string | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [picked, setPicked] = useState<string[]>([]);
  const [overlaid, setOverlaid] = useState<string | null>(null);

  const spectrum = useQuery({
    queryKey: ["spectrum", spectrumId],
    queryFn: () => {
      // Mirrors `useSpectrumBuffer`: throw rather than assert, so the guard is
      // real at runtime and not just silenced for the type checker.
      if (!spectrumId) throw new Error("No spectrum selected.");
      return getSpectrum(spectrumId);
    },
    enabled: !!spectrumId,
  });
  const buffer = useSpectrumBuffer(spectrumId);

  const match = useMutation({
    mutationFn: (id: string) => matchAgainstLibrary({ spectrum_id: id, top_k: 12 }),
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

  // Local peaks the instant a buffer lands — no network. Replaced by the
  // server's own peaks after a match, because those are what got indexed.
  const localPeaks = useMemo(() => {
    if (!buffer.data) return null;
    try {
      return detectPeaks(buffer.data);
    } catch {
      return null;
    }
  }, [buffer.data]);

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
  const overlayBuffer = useSpectrumBuffer(overlayRef?.reference.spectrum_id ?? null);

  const chartSeries = useMemo(() => {
    if (!buffer.data) return [];
    const series = [
      {
        name: "Yours",
        wavenumbers: Array.from(buffer.data.wavenumbers),
        intensities: Array.from(buffer.data.intensities),
      },
    ];
    if (overlayBuffer.data && overlayRef) {
      series.push({
        name: overlayRef.reference.compound_name,
        wavenumbers: Array.from(overlayBuffer.data.wavenumbers),
        intensities: Array.from(overlayBuffer.data.intensities),
      });
    }
    return series;
  }, [buffer.data, overlayBuffer.data, overlayRef]);

  const peakCount = result
    ? result.query_peaks.length
    : (localPeaks?.peaks.length ?? 0);

  function reset(id: string | null) {
    setSpectrumId(id);
    match.reset();
    unmix.reset();
    setPicked([]);
    setOverlaid(null);
  }

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-4">
      <header className="flex flex-col gap-3">
        <div>
          <h1 className="text-xl font-bold tracking-tight">Library</h1>
          <p className="text-muted-foreground text-sm">
            Compare a spectrum against known reference compounds to work out
            what it is.
          </p>
        </div>

        <div className="flex w-fit items-center gap-1 rounded-lg border p-1">
          {(
            [
              ["identify", "Identify a spectrum"],
              ["browse", "Browse the library"],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              onClick={() => setTask(key)}
              aria-pressed={task === key}
              className={cn(
                "min-h-8 cursor-pointer rounded-md px-3 text-xs font-medium transition-colors motion-reduce:transition-none",
                task === key
                  ? "bg-zone-library text-white"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground",
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </header>

      {task === "browse" ? (
        <BrowsePanel />
      ) : (
        <>
          <Step
            index={1}
            title="Choose your spectrum"
            hint="Pick one of your own spectra — the unknown you want to identify."
            state={spectrumId ? "done" : "active"}
          >
            {isFullUser ? (
              <div className="flex flex-wrap items-center gap-3">
                <Button size="sm" onClick={() => setPickerOpen(true)}>
                  {spectrumId ? "Choose a different one" : "Choose a spectrum"}
                </Button>
                {spectrum.data && (
                  <span className="text-muted-foreground truncate text-sm">
                    {spectrum.data.title ?? "Untitled spectrum"}
                  </span>
                )}
              </div>
            ) : (
              <div className="flex flex-wrap items-center gap-3">
                <Button size="sm" asChild>
                  <Link href="/login?next=/library">Sign in</Link>
                </Button>
                <span className="text-muted-foreground text-sm">
                  to identify your own spectra. Browsing needs no account.
                </span>
              </div>
            )}
          </Step>

          <Step
            index={2}
            title="Check the bands we found"
            hint="These peaks are what the search uses. Make sure they look like your spectrum's real bands."
            state={!spectrumId ? "locked" : peakCount > 0 ? "done" : "active"}
          >
            {buffer.isLoading ? (
              <Skeleton className="h-[280px]" />
            ) : !buffer.data ? (
              <p className="text-muted-foreground text-sm">
                This spectrum&rsquo;s data could not be loaded.
              </p>
            ) : (
              <div className="flex flex-col gap-2">
                <div className="rounded-lg border p-2">
                  <SpectrumChart
                    mode="trace"
                    height={280}
                    markers={markers}
                    series={chartSeries}
                    display={{ normalize: "max", showLegend: chartSeries.length > 1 }}
                    ariaLabel="Your spectrum with its detected bands marked"
                  />
                </div>
                <p className="text-muted-foreground text-xs">
                  {peakCount} band{peakCount === 1 ? "" : "s"}
                  {markers.length > 0 &&
                    ` · strongest at ${Math.round(
                      result?.primary_peak_cm1 ?? localPeaks?.primaryPeakCm1 ?? 0,
                    )} cm⁻¹`}
                  {!result && " · estimated on your machine"}
                </p>
              </div>
            )}
          </Step>

          <Step
            index={3}
            title="Find the closest matches"
            hint="Searches the reference library for compounds with the same bands."
            state={
              !spectrumId || peakCount === 0
                ? "locked"
                : result
                  ? "done"
                  : "active"
            }
          >
            <div className="flex flex-col gap-3">
              {!result && (
                <div>
                  <Button
                    size="sm"
                    disabled={match.isPending || !buffer.data}
                    onClick={() => spectrumId && match.mutate(spectrumId)}
                  >
                    {match.isPending ? "Searching…" : "Find matches"}
                  </Button>
                </div>
              )}

              {match.error && (
                <p className="text-destructive text-sm">
                  {match.error.message}
                </p>
              )}

              {result?.matches.length === 0 && (
                <p className="text-muted-foreground text-sm">
                  Nothing in the library resembles this spectrum yet. The
                  library is still small — publishing your own standards makes
                  it better.
                </p>
              )}

              {result && result.matches.length > 0 && (
                <>
                  <MatchList
                    result={result}
                    overlaid={overlaid}
                    onOverlay={setOverlaid}
                    picked={picked}
                    onTogglePick={togglePick}
                    showPicker={false}
                  />
                  <p className="text-muted-foreground text-xs">
                    Click a match to draw it over your spectrum. Checked{" "}
                    {result.candidates_screened} candidate
                    {result.candidates_screened === 1 ? "" : "s"}.
                  </p>
                </>
              )}
            </div>
          </Step>

          <Step
            index={4}
            title="Split a mixture"
            hint="Only needed when no single compound explains everything. Choose the components and we fit their proportions."
            state={!result ? "locked" : unmix.data ? "done" : "active"}
          >
            {result && (
              <div className="flex flex-col gap-3">
                {result.mixture_suspected ? (
                  <MixtureNotice result={result} />
                ) : (
                  <p className="text-muted-foreground text-xs">
                    The top match explains your spectrum on its own, so this
                    step is optional.
                  </p>
                )}

                {/* The chooser lives here rather than in step 3 on purpose: a
                    step that sends you back up the page to tick boxes breaks
                    the only promise the numbering makes. */}
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
                      ? "Fitting\u2026"
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
              </div>
            )}
          </Step>
        </>
      )}

      <SpectrumPickerDialog
        open={pickerOpen}
        onOpenChange={setPickerOpen}
        single
        title="Choose a spectrum"
        description="Pick the unknown you want to identify."
        confirmLabel="Use this spectrum"
        onConfirm={(ids) => {
          reset(ids[0] ?? null);
          setPickerOpen(false);
        }}
      />
    </div>
  );

  function togglePick(id: string) {
    setPicked((prev) =>
      prev.includes(id)
        ? prev.filter((p) => p !== id)
        : prev.length >= 6
          ? prev
          : [...prev, id],
    );
  }
}

function BrowsePanel() {
  const [query, setQuery] = useState("");
  const rows = useQuery({
    queryKey: ["ref-search", query],
    queryFn: () => searchReferences({ q: query || undefined, limit: 40 }),
  });

  return (
    <div className="flex flex-col gap-3">
      <Card className="p-3">
        <div className="flex items-center gap-2">
          <Search className="text-muted-foreground size-4" aria-hidden />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search by compound, mineral or formula…"
            className="h-8"
            aria-label="Search the reference library"
          />
        </div>
      </Card>

      {rows.isLoading ? (
        <Skeleton className="h-64" />
      ) : rows.error ? (
        <Card className="border-destructive/40 p-4">
          <p className="text-destructive text-sm">
            {rows.error.message}
          </p>
        </Card>
      ) : !rows.data?.length ? (
        <EmptyCard
          icon={Library}
          message={
            query
              ? "No references match that search."
              : "The reference library is empty. Seed it with `make seed-library`, or publish your own standards into it."
          }
        />
      ) : (
        <Card className="gap-0 p-0">
          <ul className="divide-y">
            {rows.data.map((row) => (
              <ReferenceRow key={row.id} row={row} />
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}
