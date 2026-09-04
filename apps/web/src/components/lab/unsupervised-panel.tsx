"use client";

import { useMemo, useState } from "react";
import { Info } from "lucide-react";

import type { Dataset } from "@ramanhub/api-client";
import { analyzePca } from "@ramanhub/processing";
import { cn } from "@ramanhub/ui";
import { Button } from "@ramanhub/ui/button";
import { Card } from "@ramanhub/ui/card";
import { Label } from "@ramanhub/ui/label";
import { Skeleton } from "@ramanhub/ui/skeleton";

import { SpectrumChart } from "~/components/charts/spectrum-chart";
import { useDatasetBuffers } from "~/lib/spectra-buffer";

/**
 * Unsupervised analysis over the open dataset: PCA, optionally with k-means on
 * the scores.
 *
 * This computes in the browser, from the spectra already buffered for the lab.
 * That is not a shortcut around the analysis API — it is what the API asks
 * for. Hosted execution is refused with a 409, and a `local` run only records
 * a signed job envelope describing the computation, because the design puts
 * the numbers on the analyst's machine. The analyst's machine is this one.
 *
 * The consequence is stated in the UI rather than hidden: these results are
 * exploratory and are not recorded as an `AnalysisRun`. Anything citable needs
 * provenance the browser can't vouch for.
 */

/** Distinct enough to read at a glance, and stable per cluster index. */
const CLUSTER_COLORS = [
  "var(--chart-1)",
  "var(--chart-2)",
  "var(--chart-3)",
  "var(--chart-4)",
  "var(--chart-5)",
];

const SCATTER = { width: 520, height: 320, pad: 40 };

function ScoresScatter({
  scores,
  labels,
  clusterLabels,
  xLabel,
  yLabel,
}: {
  scores: number[][];
  labels: string[];
  clusterLabels: number[] | undefined;
  xLabel: string;
  yLabel: string;
}) {
  const { width, height, pad } = SCATTER;
  const points = scores.map((row) => [row[0] ?? 0, row[1] ?? 0] as const);

  const xs = points.map((p) => p[0]);
  const ys = points.map((p) => p[1]);
  // Pad the extent so points never sit on the axis line, and guard the
  // degenerate case where every score is identical.
  const span = (values: number[]) => {
    const lo = Math.min(...values);
    const hi = Math.max(...values);
    const margin = (hi - lo || 1) * 0.1;
    return [lo - margin, hi + margin] as const;
  };
  const [x0, x1] = span(xs);
  const [y0, y1] = span(ys);

  const px = (v: number) => pad + ((v - x0) / (x1 - x0)) * (width - 2 * pad);
  const py = (v: number) =>
    height - pad - ((v - y0) / (y1 - y0)) * (height - 2 * pad);

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="h-auto w-full"
      role="img"
      aria-label={`Scores scatter of ${xLabel} against ${yLabel} for ${labels.length} spectra`}
    >
      {/* Zero lines: PCA scores are centred, so the origin is meaningful. */}
      {x0 < 0 && x1 > 0 && (
        <line
          x1={px(0)}
          y1={pad}
          x2={px(0)}
          y2={height - pad}
          stroke="var(--border)"
          strokeDasharray="3 3"
        />
      )}
      {y0 < 0 && y1 > 0 && (
        <line
          x1={pad}
          y1={py(0)}
          x2={width - pad}
          y2={py(0)}
          stroke="var(--border)"
          strokeDasharray="3 3"
        />
      )}
      <line
        x1={pad}
        y1={height - pad}
        x2={width - pad}
        y2={height - pad}
        stroke="var(--border)"
      />
      <line
        x1={pad}
        y1={pad}
        x2={pad}
        y2={height - pad}
        stroke="var(--border)"
      />

      {points.map((p, i) => {
        const cluster = clusterLabels?.[i];
        const fill =
          cluster == null
            ? "var(--chart-1)"
            : (CLUSTER_COLORS[cluster % CLUSTER_COLORS.length] ??
              "var(--chart-1)");
        return (
          <g key={labels[i] ?? i}>
            <circle cx={px(p[0])} cy={py(p[1])} r={5} fill={fill} />
            <text
              x={px(p[0]) + 8}
              y={py(p[1]) + 3}
              fontSize={10}
              fill="var(--muted-foreground)"
            >
              {labels[i]}
            </text>
          </g>
        );
      })}

      <text
        x={width / 2}
        y={height - 8}
        fontSize={11}
        textAnchor="middle"
        fill="var(--muted-foreground)"
      >
        {xLabel}
      </text>
      <text
        x={12}
        y={height / 2}
        fontSize={11}
        textAnchor="middle"
        fill="var(--muted-foreground)"
        transform={`rotate(-90 12 ${height / 2})`}
      >
        {yLabel}
      </text>
    </svg>
  );
}

function NumberField({
  id,
  label,
  value,
  min,
  max,
  onChange,
}: {
  id: string;
  label: string;
  value: number;
  min: number;
  max: number;
  onChange: (v: number) => void;
}) {
  return (
    <div className="space-y-1">
      <Label htmlFor={id} className="text-xs">
        {label}
      </Label>
      <input
        id={id}
        type="number"
        min={min}
        max={max}
        value={value}
        onChange={(e) => {
          const n = Number(e.target.value);
          if (Number.isFinite(n)) onChange(n);
        }}
        className="border-input bg-background focus-visible:ring-ring/50 h-8 w-24 rounded-md border px-2 text-sm focus-visible:ring-[3px] focus-visible:outline-none"
      />
    </div>
  );
}

export function UnsupervisedPanel({
  dataset,
  titleFor,
}: {
  dataset: Dataset | undefined;
  /** Short display label for a spectrum id, for plot annotations. */
  titleFor: (spectrumId: string) => string;
}) {
  const [components, setComponents] = useState(2);
  const [gridPoints, setGridPoints] = useState(128);
  const [clustering, setClustering] = useState(false);
  const [clusters, setClusters] = useState(2);

  const memberIds = useMemo(
    () => dataset?.spectra.map((s) => s.id) ?? [],
    [dataset],
  );
  const { ready, loading, failed } = useDatasetBuffers(memberIds);

  const result = useMemo(() => {
    if (ready.length < 2) return null;
    try {
      return {
        ok: true as const,
        value: analyzePca(
          ready.map(({ id, buffer }) => ({
            id,
            label: titleFor(id),
            wavenumbers: buffer.wavenumbers,
            intensities: buffer.intensities,
          })),
          {
            components,
            gridPoints,
            clusters: clustering ? clusters : null,
          },
        ),
      };
    } catch (e) {
      return {
        ok: false as const,
        message:
          e instanceof Error ? e.message : "This analysis could not be run.",
      };
    }
  }, [ready, titleFor, components, gridPoints, clustering, clusters]);

  if (!dataset) {
    return (
      <Card className="text-muted-foreground flex h-[320px] flex-col items-center justify-center gap-1 p-6 text-center text-sm">
        <span className="font-medium">Pick a dataset</span>
        <span className="text-xs">
          Unsupervised analysis compares spectra, so it runs over a whole
          dataset rather than one file.
        </span>
      </Card>
    );
  }

  if (dataset.spectra.length < 2) {
    return (
      <Card className="text-muted-foreground flex h-[320px] flex-col items-center justify-center gap-1 p-6 text-center text-sm">
        <span className="font-medium">
          {dataset.name} needs at least two spectra
        </span>
        <span className="text-xs">Add more from the list to compare them.</span>
      </Card>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <Card className="gap-3 p-4">
        <div className="flex flex-wrap items-end gap-4">
          <NumberField
            id="pca-components"
            label="Components"
            value={components}
            min={2}
            max={10}
            onChange={setComponents}
          />
          <NumberField
            id="pca-grid"
            label="Grid points"
            value={gridPoints}
            min={16}
            max={512}
            onChange={setGridPoints}
          />
          <div className="space-y-1">
            <Label className="text-xs">Clustering</Label>
            <Button
              type="button"
              size="sm"
              variant={clustering ? "default" : "outline"}
              onClick={() => setClustering((v) => !v)}
            >
              k-means {clustering ? "on" : "off"}
            </Button>
          </div>
          {clustering && (
            <NumberField
              id="pca-clusters"
              label="Clusters"
              value={clusters}
              min={2}
              max={Math.max(2, ready.length)}
              onChange={setClusters}
            />
          )}
        </div>

        <p className="text-muted-foreground flex items-start gap-1.5 text-xs">
          <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          <span>
            Computed on your machine from the {ready.length} spectra held in
            memory. Exploratory only — this is not recorded as an analysis run,
            so it isn&apos;t citable.
          </span>
        </p>
      </Card>

      {loading && ready.length < 2 ? (
        <Skeleton className="h-[320px] w-full rounded-xl" />
      ) : result === null ? (
        <Card className="text-muted-foreground p-6 text-center text-sm">
          Could not load enough spectra to compare
          {failed > 0 ? ` (${failed} failed to load)` : ""}.
        </Card>
      ) : !result.ok ? (
        <Card className="p-6 text-center text-sm">
          <p className="text-foreground/80">{result.message}</p>
        </Card>
      ) : (
        <>
          <Card className="gap-3 p-4">
            <h3 className="text-sm font-semibold">Scores</h3>
            <ScoresScatter
              scores={result.value.scores}
              labels={result.value.labels}
              clusterLabels={result.value.clusterLabels}
              xLabel={`PC1 · ${((result.value.explainedVarianceRatio[0] ?? 0) * 100).toFixed(1)}% of variance`}
              yLabel={`PC2 · ${((result.value.explainedVarianceRatio[1] ?? 0) * 100).toFixed(1)}%`}
            />
          </Card>

          <div className="grid gap-3 md:grid-cols-2">
            <Card className="gap-3 p-4">
              <h3 className="text-sm font-semibold">Explained variance</h3>
              <ul className="space-y-2">
                {result.value.explainedVarianceRatio.map((ratio, i) => (
                  <li key={i} className="space-y-1">
                    <div className="flex justify-between text-xs">
                      <span className="text-muted-foreground">PC{i + 1}</span>
                      <span className="font-mono">
                        {(ratio * 100).toFixed(1)}%
                      </span>
                    </div>
                    <div className="bg-muted h-1.5 w-full overflow-hidden rounded-full">
                      <div
                        className="bg-primary h-full rounded-full"
                        style={{ width: `${Math.max(ratio * 100, 0.5)}%` }}
                      />
                    </div>
                  </li>
                ))}
              </ul>
              <p className="text-muted-foreground text-xs">
                Cumulative:{" "}
                {(
                  result.value.explainedVarianceRatio.reduce(
                    (a, b) => a + b,
                    0,
                  ) * 100
                ).toFixed(1)}
                %
              </p>
            </Card>

            <Card className="gap-3 p-4">
              <h3 className="text-sm font-semibold">Loadings</h3>
              <SpectrumChart
                mode="trace"
                series={result.value.components.map((values, i) => ({
                  name: `PC${i + 1}`,
                  wavenumbers: result.value.grid,
                  intensities: values,
                }))}
                height={240}
                ariaLabel="PCA loading vectors over the shared wavenumber grid"
              />
              <p className="text-muted-foreground text-xs">
                Where along the axis each component separates the spectra.
              </p>
            </Card>
          </div>

          {result.value.clusterLabels && (
            <Card className="gap-2 p-4">
              <h3 className="text-sm font-semibold">Clusters</h3>
              <div className="flex flex-wrap gap-2">
                {result.value.labels.map((label, i) => {
                  const cluster = result.value.clusterLabels?.[i] ?? 0;
                  return (
                    <span
                      key={label}
                      className={cn(
                        "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs",
                      )}
                    >
                      <span
                        className="size-2 rounded-full"
                        style={{
                          background:
                            CLUSTER_COLORS[cluster % CLUSTER_COLORS.length],
                        }}
                        aria-hidden
                      />
                      {label}
                      <span className="text-muted-foreground">
                        #{cluster + 1}
                      </span>
                    </span>
                  );
                })}
              </div>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
