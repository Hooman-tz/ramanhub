"use client";

import { useCallback, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Maximize2, Minus, Plus, RotateCcw } from "lucide-react";

import { getMyLibrary } from "@ramanhub/api-client";
import { cn } from "@ramanhub/ui";
import { Button } from "@ramanhub/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@ramanhub/ui/dialog";
import { Skeleton } from "@ramanhub/ui/skeleton";

import type { SpectrumDisplayOptions } from "./plot-controls";
import type { ZoomRange } from "./spectrum-chart";
import { useDatasetBuffers } from "~/lib/spectra-buffer";
import { DEFAULT_DISPLAY_OPTIONS, PlotControls } from "./plot-controls";
import { FULL_ZOOM, SpectrumChart } from "./spectrum-chart";

export interface ExplorerSpectrum {
  spectrum_id: string;
  label: string | null;
}

/** How much of the current window one zoom-button press removes / restores. */
const ZOOM_STEP = 0.2;
const MIN_WINDOW = 0.5; // percent — stops the buttons zooming to a single point

function zoomBy(range: ZoomRange, direction: 1 | -1): ZoomRange {
  const span = range.end - range.start;
  const centre = range.start + span / 2;
  const nextSpan =
    direction === 1
      ? Math.max(MIN_WINDOW, span * (1 - ZOOM_STEP))
      : Math.min(100, span / (1 - ZOOM_STEP));
  // Keep the window inside [0, 100] by sliding rather than clipping, so a
  // zoom-out near an edge widens instead of silently doing nothing.
  let start = centre - nextSpan / 2;
  let end = centre + nextSpan / 2;
  if (start < 0) {
    end -= start;
    start = 0;
  }
  if (end > 100) {
    start -= end - 100;
    end = 100;
  }
  return { start: Math.max(0, start), end: Math.min(100, end) };
}

/**
 * The full-size data explorer: every trace on one chart, zoomable, with the
 * plot controls the lab uses.
 *
 * A post's gallery shows one spectrum per panel at reading size, which is the
 * right default for scanning but useless for actually looking at a peak. This
 * is the "look closer" affordance — overlay or stack the traces, normalise
 * them for shape comparison, and zoom into a band.
 *
 * Reads through `useDatasetBuffers`, the same cache the Data Lab fills, so a
 * spectrum already opened in the lab draws here without a request.
 */
export function SpectrumExplorer({
  spectra,
  title,
  trigger,
  footer,
}: {
  spectra: ExplorerSpectrum[];
  title: string;
  /** Custom trigger; defaults to a compact "Explore data" button. */
  trigger?: React.ReactNode;
  /** Rendered under the controls — used for the "Fork to my lab" call to action. */
  footer?: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        {trigger ?? (
          <Button
            variant="outline"
            size="sm"
            className="cursor-pointer gap-1.5"
          >
            <Maximize2 className="size-3.5" aria-hidden />
            Explore data
          </Button>
        )}
      </DialogTrigger>
      <DialogContent className="max-h-[92vh] gap-3 overflow-y-auto sm:max-w-5xl">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>
            Zoom with the scroll wheel or the slider, or use the buttons below.
            Drag to pan.
          </DialogDescription>
        </DialogHeader>
        {/* Mounted only while open so N spectra aren't fetched behind a closed
            dialog on every post page. */}
        {open && <ExplorerBody spectra={spectra} footer={footer} />}
      </DialogContent>
    </Dialog>
  );
}

function ExplorerBody({
  spectra,
  footer,
}: {
  spectra: ExplorerSpectrum[];
  footer?: React.ReactNode;
}) {
  const [display, setDisplay] = useState<SpectrumDisplayOptions>(
    DEFAULT_DISPLAY_OPTIONS,
  );
  const [zoomRange, setZoomRange] = useState<ZoomRange>(FULL_ZOOM);
  const [hidden, setHidden] = useState<Set<string>>(() => new Set());

  const ids = useMemo(() => spectra.map((s) => s.spectrum_id), [spectra]);
  const { ready, loading, failed } = useDatasetBuffers(ids);

  // Titles for anything the caller didn't label. Same key the picker uses, so
  // it is usually already in cache.
  const library = useQuery({
    queryKey: ["my-library", "picker"],
    queryFn: () => getMyLibrary({ limit: 200 }),
    staleTime: 60_000,
  });

  const labelFor = useCallback(
    (id: string) => {
      const given = spectra.find((s) => s.spectrum_id === id)?.label;
      if (given) return given;
      const found = library.data?.find((s) => s.id === id);
      return found?.title ?? id.slice(0, 8);
    },
    [spectra, library.data],
  );

  const series = useMemo(
    () =>
      ready
        .filter(({ id }) => !hidden.has(id))
        .map(({ id, buffer }) => ({
          name: labelFor(id),
          wavenumbers: Array.from(buffer.wavenumbers),
          intensities: Array.from(buffer.intensities),
        })),
    [ready, hidden, labelFor],
  );

  const toggle = (id: string) =>
    setHidden((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const atFullZoom = zoomRange.start <= 0 && zoomRange.end >= 100;
  const windowSpan = zoomRange.end - zoomRange.start;

  return (
    <div className="space-y-3">
      <div className="border-border bg-card rounded-lg border p-2">
        {loading && ready.length === 0 ? (
          <Skeleton className="h-[420px] w-full rounded-md" />
        ) : series.length > 0 ? (
          <SpectrumChart
            mode="trace"
            series={series}
            display={display}
            zoom
            zoomRange={zoomRange}
            onZoomChange={setZoomRange}
            height={420}
            ariaLabel={`${series.length} spectra, showing wavenumbers ${zoomRange.start.toFixed(0)}% to ${zoomRange.end.toFixed(0)}% of the full range`}
          />
        ) : (
          <p className="text-muted-foreground px-2 py-16 text-center text-sm">
            {ready.length === 0
              ? "Couldn't read a chartable trace for any of these spectra."
              : "Every trace is hidden — turn one back on below."}
          </p>
        )}
      </div>

      {/* Zoom controls. The wheel and the slider are conveniences; these are
          the guaranteed, keyboard-reachable route to the same result. */}
      <div
        className="flex flex-wrap items-center gap-2"
        role="group"
        aria-label="Zoom"
      >
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="size-9 cursor-pointer p-0"
          aria-label="Zoom in"
          disabled={windowSpan <= MIN_WINDOW}
          onClick={() => setZoomRange((r) => zoomBy(r, 1))}
        >
          <Plus className="size-4" aria-hidden />
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="size-9 cursor-pointer p-0"
          aria-label="Zoom out"
          disabled={atFullZoom}
          onClick={() => setZoomRange((r) => zoomBy(r, -1))}
        >
          <Minus className="size-4" aria-hidden />
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-9 cursor-pointer gap-1.5"
          disabled={atFullZoom}
          onClick={() => setZoomRange(FULL_ZOOM)}
        >
          <RotateCcw className="size-3.5" aria-hidden />
          Reset zoom
        </Button>
        <span
          className="text-muted-foreground text-xs tabular-nums"
          aria-live="polite"
        >
          {atFullZoom ? "Full range" : `Showing ${windowSpan.toFixed(0)}%`}
        </span>
      </div>

      <PlotControls
        value={display}
        onChange={setDisplay}
        // Zoom owns the x-axis now; two competing crop mechanisms would fight.
        hideXRange
      />

      {spectra.length > 1 && (
        <fieldset className="border-border rounded-lg border p-2.5">
          <legend className="text-muted-foreground px-1 text-xs">
            Traces ({series.length} of {spectra.length} shown)
          </legend>
          <ul className="flex flex-wrap gap-1.5">
            {ids.map((id) => {
              const shown = !hidden.has(id);
              return (
                <li key={id}>
                  <button
                    type="button"
                    aria-pressed={shown}
                    onClick={() => toggle(id)}
                    className={cn(
                      "h-9 cursor-pointer rounded-md border px-2.5 text-xs font-medium transition-colors duration-150 motion-reduce:transition-none",
                      "focus-visible:ring-ring/50 focus-visible:ring-[3px] focus-visible:outline-none",
                      shown
                        ? "border-primary bg-primary/10 text-primary"
                        : "border-input bg-background text-muted-foreground hover:bg-accent hover:text-accent-foreground",
                    )}
                  >
                    {labelFor(id)}
                  </button>
                </li>
              );
            })}
          </ul>
        </fieldset>
      )}

      {failed > 0 && (
        <p className="text-muted-foreground text-xs">
          {failed} {failed === 1 ? "spectrum" : "spectra"} could not be loaded.
        </p>
      )}

      {footer}
    </div>
  );
}
