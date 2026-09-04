"use client";

import { useEffect, useRef } from "react";
// Tree-shaken ECharts: only the line chart + the handful of components these
// two chart modes use, rather than `import * as echarts from "echarts"` which
// pulls every chart type into the web bundle.
import { LineChart } from "echarts/charts";
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkAreaComponent,
  MarkLineComponent,
  TooltipComponent,
} from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";

import { useTheme } from "@ramanhub/ui/theme";

echarts.use([
  LineChart,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  MarkAreaComponent,
  MarkLineComponent,
  DataZoomComponent,
  CanvasRenderer,
]);

/** A labelled vertical guide at one wavenumber. */
export interface PeakMarker {
  cm1: number;
  label?: string;
}

export interface TraceSeries {
  name: string;
  wavenumbers: number[];
  intensities: number[];
}

/**
 * Display-only view options for the trace chart. Every field is optional and
 * defaults to a no-op, so existing callers that don't pass `display` render
 * exactly as before. Normalisation is applied to a *copy* of the caller's
 * arrays — the source data is never mutated.
 */
export interface SpectrumDisplayOptions {
  /** Waterfall the traces, each shifted up by `offset * seriesIndex`. */
  stacked?: boolean;
  /** Vertical gap between stacked traces, in intensity units. */
  offset?: number;
  /** Per-series intensity rescale, for shape comparison. Display only. */
  normalize?: "none" | "max" | "minmax" | "area";
  /** Crop the wavenumber axis to `[xMin, xMax]` (either end optional). */
  xMin?: number;
  xMax?: number;
  /** Force the legend on/off (otherwise it shows when there is >1 series). */
  showLegend?: boolean;
  /** Toggle the axis split lines. */
  showGrid?: boolean;
  /** Line stroke width for every trace. */
  lineWidth?: number;
}

/** Baseline `SpectrumDisplayOptions` — a completely neutral view. */
export const DEFAULT_DISPLAY_OPTIONS: SpectrumDisplayOptions = {
  stacked: false,
  offset: 0,
  normalize: "none",
  showLegend: true,
  showGrid: true,
  lineWidth: 2,
};

/**
 * A zoom window over the wavenumber axis, as percentages of the full range.
 * `{ start: 0, end: 100 }` is "fully zoomed out".
 *
 * Percent rather than absolute cm⁻¹ because that is ECharts' own dataZoom
 * unit, and because it keeps the reset value constant regardless of what data
 * happens to be loaded.
 */
export interface ZoomRange {
  start: number;
  end: number;
}

export const FULL_ZOOM: ZoomRange = { start: 0, end: 100 };

type SpectrumChartProps = {
  /**
   * Height for the chart canvas — a pixel number, or any CSS length. Pass
   * `"100%"` to fill a parent that has a definite height; a `ResizeObserver`
   * keeps ECharts in step as that height changes.
   */
  height?: number | string;
  /** Show ECharts' built-in loading spinner. */
  loading?: boolean;
  /** Accessible label — the chart canvas gets `role="img"`. */
  ariaLabel?: string;
  /**
   * Enable wheel/drag zoom plus a slider under the x-axis. Off by default so
   * the feed and other read-only cards keep their current lightweight
   * behaviour and bundle cost.
   *
   * Zoom must never be the ONLY way to reach a region: pair this with visible,
   * keyboard-reachable zoom-in / zoom-out / reset controls (see
   * `SpectrumExplorer`), which is what makes the chart usable without a mouse.
   */
  zoom?: boolean;
  /** Controlled zoom window. Only meaningful when `zoom` is set. */
  zoomRange?: ZoomRange;
  /** Fired when the user zooms or pans with the mouse. */
  onZoomChange?: (range: ZoomRange) => void;
} & (
  | {
      mode: "trace";
      /**
       * Vertical guides at given wavenumbers — detected peaks, in practice.
       * Purely annotational: they do not affect scaling, the legend, or the
       * tooltip, so adding them cannot change how the data itself reads.
       */
      markers?: PeakMarker[];
      /**
       * The single line to draw. Optional only because `series` replaces it:
       * pass either these two, or `series`. Callers used to hand over dummy
       * arrays alongside `series` to satisfy the type; they no longer need to.
       */
      wavenumbers?: number[];
      intensities?: number[];
      /**
       * A second line drawn on its own right-hand axis — raw vs processed
       * intensities routinely differ by orders of magnitude, so sharing one
       * axis would flatten the smaller series into the baseline. Only used on
       * the single-line path (i.e. when `series` is not supplied).
       */
      overlay?: TraceSeries;
      /**
       * N independent traces, each its own legend entry and palette colour.
       * When supplied and non-empty this REPLACES the single
       * `wavenumbers`/`intensities` line (those props stay required by the
       * type but are ignored). Legend appears once there is >1 series and is
       * click-to-toggle; the tooltip is axis-triggered across every visible
       * series.
       */
      series?: TraceSeries[];
      /** Display-only view options; never mutates the caller's arrays. */
      display?: SpectrumDisplayOptions;
    }
  | {
      mode: "band";
      grid: number[];
      mean: number[];
      std: number[];
    }
);

function resolveColors() {
  const s = getComputedStyle(document.documentElement);
  const token = (name: string, fallback: string) =>
    s.getPropertyValue(name).trim() || fallback;
  return {
    mean: token("--chart-mean", "#2a78d6"),
    band: token("--chart-band", "rgba(42,120,214,0.18)"),
    grid: token("--chart-grid", "#e1e0d9"),
    axis: token("--chart-axis", "#898781"),
    // Theme-aware tooltip surface (was hardcoded white/near-black — unreadable
    // and jarring in dark mode).
    surface: token("--popover", "#ffffff"),
    ink: token("--popover-foreground", "#0b0b0b"),
    border: token("--border", "#e1e0d9"),
    // Categorical palette for the N-series trace mode. These flip with the
    // theme (light hex / dark oklch) via `tooling/tailwind/theme.css`.
    palette: [
      token("--chart-1", "#0d6b6e"),
      token("--chart-2", "#2f8f92"),
      token("--chart-3", "#5bb3b5"),
      token("--chart-4", "#b45309"),
      token("--chart-5", "#1e40af"),
    ],
  };
}

const AXIS_NAME = "Raman shift (cm⁻¹)";

/**
 * `#rgb` / `#rrggbb` → `rgba(r, g, b, alpha)`. Returns `null` when the input
 * isn't a plain hex string (e.g. it's already `rgb()` / `oklch()`), so callers
 * can fall back to a token colour.
 */
function hexToRgba(hex: string, alpha: number): string | null {
  const m = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(hex.trim());
  if (!m?.[1]) return null;
  let h = m[1];
  if (h.length === 3)
    h = h
      .split("")
      .map((ch) => ch + ch)
      .join("");
  const int = Number.parseInt(h, 16);
  const r = (int >> 16) & 255;
  const g = (int >> 8) & 255;
  const b = int & 255;
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function fmt(v: number | undefined): string {
  if (v === undefined || !Number.isFinite(v)) return "—";
  const abs = Math.abs(v);
  if (abs !== 0 && (abs < 1e-3 || abs >= 1e5)) return v.toExponential(2);
  return v.toPrecision(4).replace(/\.?0+$/, "");
}

/**
 * Return a rescaled COPY of `ys` for display. Never mutates the input. Uses a
 * single pass (no `Math.max(...spread)` — spectra can be tens of thousands of
 * points and that overflows the call stack).
 */
function normalizeIntensities(
  ys: number[],
  mode: "max" | "minmax" | "area",
): number[] {
  let min = Infinity;
  let max = -Infinity;
  let absMax = 0;
  let absSum = 0;
  for (const y of ys) {
    if (!Number.isFinite(y)) continue;
    if (y < min) min = y;
    if (y > max) max = y;
    const a = Math.abs(y);
    if (a > absMax) absMax = a;
    absSum += a;
  }
  if (!Number.isFinite(min) || !Number.isFinite(max)) return ys.slice();
  if (mode === "max") return absMax ? ys.map((y) => y / absMax) : ys.slice();
  if (mode === "area") return absSum ? ys.map((y) => y / absSum) : ys.slice();
  const span = max - min;
  return span ? ys.map((y) => (y - min) / span) : ys.slice();
}

/** Zip two number arrays into `[x, y]` pairs, dropping any ragged tail. */
function zip(xs: number[], ys: number[]): [number, number][] {
  const out: [number, number][] = [];
  const n = Math.min(xs.length, ys.length);
  for (let i = 0; i < n; i++) {
    const x = xs[i];
    const y = ys[i];
    if (x === undefined || y === undefined) continue;
    out.push([x, y]);
  }
  return out;
}

export function SpectrumChart(props: SpectrumChartProps) {
  const {
    height = 320,
    loading = false,
    ariaLabel,
    zoom = false,
    zoomRange,
    onZoomChange,
  } = props;
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);
  const { resolvedTheme } = useTheme();

  // The draw effect seeds the initial zoom window from this ref rather than
  // depending on `zoomRange` directly. A wheel tick would otherwise re-run a
  // `notMerge` redraw on every frame; instead the sync effect below nudges the
  // existing chart with `dispatchAction`, which is cheap.
  const zoomRangeRef = useRef<ZoomRange>(zoomRange ?? FULL_ZOOM);
  zoomRangeRef.current = zoomRange ?? FULL_ZOOM;
  // Same reason: keep the callback out of the draw effect's dependency list so
  // an inline arrow from the parent can't force a redraw every render.
  const onZoomChangeRef = useRef(onZoomChange);
  onZoomChangeRef.current = onZoomChange;

  // Narrowed, referentially-stable data handles (the arrays come straight
  // from React Query cache) so the draw effect only re-runs on real change.
  const mode = props.mode;
  const grid = props.mode === "band" ? props.grid : undefined;
  const meanArr = props.mode === "band" ? props.mean : undefined;
  const stdArr = props.mode === "band" ? props.std : undefined;
  const wavenumbers = props.mode === "trace" ? props.wavenumbers : undefined;
  const intensities = props.mode === "trace" ? props.intensities : undefined;
  const overlay = props.mode === "trace" ? props.overlay : undefined;
  const seriesProp = props.mode === "trace" ? props.series : undefined;
  const markers = props.mode === "trace" ? props.markers : undefined;
  const displayProp = props.mode === "trace" ? props.display : undefined;
  // Spread `display` into primitive handles so the draw effect only re-runs on
  // a real value change, not on a fresh object identity each render.
  const hasDisplay = displayProp !== undefined;
  const dStacked = displayProp?.stacked;
  const dOffset = displayProp?.offset;
  const dNormalize = displayProp?.normalize;
  const dXMin = displayProp?.xMin;
  const dXMax = displayProp?.xMax;
  const dShowLegend = displayProp?.showLegend;
  const dShowGrid = displayProp?.showGrid;
  const dLineWidth = displayProp?.lineWidth;

  // init once / dispose on unmount
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    // React 19 StrictMode double-invokes this effect in dev; make sure a
    // prior instance on this node is gone before re-initialising.
    echarts.getInstanceByDom(el)?.dispose();
    const chart = echarts.init(el);
    chartRef.current = chart;

    // The container often has 0 width on the very first paint (inside a card
    // that's still laying out). One deferred resize catches that case.
    const raf = requestAnimationFrame(() => {
      if (!chart.isDisposed()) chart.resize();
    });
    const ro = new ResizeObserver(() => {
      if (!chart.isDisposed()) chart.resize();
    });
    ro.observe(el);

    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      chart.dispose();
      chartRef.current = null;
    };
  }, []);

  // (re)draw when data, loading, or the resolved theme changes
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;

    if (loading) {
      chart.showLoading();
      return;
    }
    chart.hideLoading();

    const c = resolveColors();
    const axisStyle = {
      nameTextStyle: { color: c.axis },
      axisLabel: { color: c.axis },
      axisLine: { lineStyle: { color: c.grid } },
      splitLine: {
        lineStyle: { color: c.grid, type: "dashed" as const, opacity: 0.5 },
      },
    };
    const compact = typeof height === "number" && height <= 200;

    // `filterMode: "none"` keeps every point in the series and only moves the
    // axis window. The alternative ("filter") drops out-of-window points and
    // rescales y to whatever is left, which makes peak heights jump around as
    // you pan — the opposite of what you want when comparing peaks.
    const dataZoom = zoom
      ? [
          {
            type: "inside" as const,
            xAxisIndex: 0,
            filterMode: "none" as const,
            start: zoomRangeRef.current.start,
            end: zoomRangeRef.current.end,
          },
          {
            type: "slider" as const,
            xAxisIndex: 0,
            filterMode: "none" as const,
            start: zoomRangeRef.current.start,
            end: zoomRangeRef.current.end,
            height: 22,
            bottom: 8,
            borderColor: c.grid,
            fillerColor: hexToRgba(c.mean, 0.12) ?? c.band,
            handleStyle: { color: c.mean },
            moveHandleStyle: { color: c.mean },
            textStyle: { color: c.axis },
            dataBackground: {
              lineStyle: { color: c.grid },
              areaStyle: { color: c.band },
            },
          },
        ]
      : undefined;
    // The slider needs its own strip of space under the axis label.
    const gridBottom = zoom ? 88 : 44;

    // Respect the OS "reduce motion" setting — no entrance animation then.
    const reducedMotion =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const drawAnimation = {
      animation: !reducedMotion,
      animationDuration: 400,
      animationEasing: "cubicOut" as const,
    };

    // Soft gradient area fill under the primary line — colour derived from the
    // mean-line token, fading to transparent at the baseline.
    const fillTop = hexToRgba(c.mean, 0.22) ?? c.band;
    const fillBottom = hexToRgba(c.mean, 0) ?? "rgba(0, 0, 0, 0)";
    const areaFill = {
      color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
        { offset: 0, color: fillTop },
        { offset: 1, color: fillBottom },
      ]),
      opacity: 1,
    };
    const baseTooltip = {
      // `confine` keeps the tooltip inside the chart box — without it, a
      // small chart in a feed card throws the tooltip outside/over the card
      // ("funny on hover").
      confine: true,
      appendToBody: false,
      backgroundColor: c.surface,
      borderColor: c.border,
      borderWidth: 1,
      borderRadius: 10,
      padding: [6, 10],
      textStyle: { color: c.ink, fontSize: 12 },
      extraCssText: "box-shadow: 0 4px 12px rgba(0,0,0,0.12);",
    };
    const baseTextStyle = {
      fontFamily: 'system-ui, -apple-system, "Segoe UI", sans-serif',
    };

    if (mode === "band" && grid && meanArr && stdArr) {
      const lower = zip(
        grid,
        grid.map((_, i) => (meanArr[i] ?? 0) - (stdArr[i] ?? 0)),
      );
      const width = zip(
        grid,
        grid.map((_, i) => 2 * (stdArr[i] ?? 0)),
      );
      const meanLine = zip(grid, meanArr);

      chart.setOption(
        {
          ...drawAnimation,
          textStyle: baseTextStyle,
          dataZoom,
          grid: { left: 56, right: 20, top: 16, bottom: gridBottom },
          tooltip: {
            ...baseTooltip,
            trigger: "axis",
            axisPointer: { type: "line", lineStyle: { color: c.axis } },
            formatter: (params: unknown) => {
              const arr = params as { dataIndex: number }[];
              const i = arr[0]?.dataIndex ?? 0;
              return (
                `${fmt(grid[i])} cm⁻¹<br/>` +
                `mean ${fmt(meanArr[i])} ± ${fmt(stdArr[i])}`
              );
            },
          },
          xAxis: {
            type: "value",
            scale: true,
            name: AXIS_NAME,
            nameLocation: "middle",
            nameGap: 26,
            ...axisStyle,
          },
          yAxis: {
            type: "value",
            scale: true,
            name: "Intensity",
            nameLocation: "middle",
            nameGap: 40,
            ...axisStyle,
          },
          series: [
            {
              type: "line",
              name: "lower",
              data: lower,
              stack: "band",
              symbol: "none",
              lineStyle: { opacity: 0 },
              silent: true,
              z: 1,
            },
            {
              type: "line",
              name: "±1 SD",
              data: width,
              stack: "band",
              symbol: "none",
              lineStyle: { opacity: 0 },
              areaStyle: { color: c.band },
              silent: true,
              z: 1,
            },
            {
              type: "line",
              name: "mean",
              data: meanLine,
              symbol: "none",
              sampling: "lttb",
              lineStyle: { width: 2.25, color: c.mean },
              itemStyle: { color: c.mean },
              areaStyle: areaFill,
              emphasis: { focus: "series" },
              z: 3,
            },
          ],
        },
        { notMerge: true },
      );
      return;
    }

    const multiSeries = seriesProp !== undefined && seriesProp.length > 0;
    // Either shape is enough to draw: the single line, or `series`.
    if (mode === "trace" && ((wavenumbers && intensities) || multiSeries)) {

      // ---- Legacy path: single trace (+ optional dual-axis overlay). ----
      // Byte-for-byte identical to before, so every existing caller (the
      // `spectra/[id]` viewer, findings overlay, feed cards) is untouched.
      if (!multiSeries && !hasDisplay && wavenumbers && intensities) {
        const series: Record<string, unknown>[] = [
          {
            type: "line",
            name: overlay ? "Processed" : "Intensity",
            data: zip(wavenumbers, intensities),
            showSymbol: false,
            sampling: "lttb",
            smooth: 0.15,
            lineStyle: { width: 2.25, color: c.mean },
            itemStyle: { color: c.mean },
            areaStyle: areaFill,
            emphasis: { focus: "series" },
            yAxisIndex: 0,
            z: 3,
          },
        ];
        if (overlay) {
          series.push({
            type: "line",
            name: overlay.name,
            data: zip(overlay.wavenumbers, overlay.intensities),
            showSymbol: false,
            sampling: "lttb",
            lineStyle: {
              width: 1.25,
              type: "dashed",
              color: c.axis,
              opacity: 0.85,
            },
            itemStyle: { color: c.axis },
            yAxisIndex: 1,
            z: 1,
          });
        }

        chart.setOption(
          {
            ...drawAnimation,
            textStyle: baseTextStyle,
            legend: overlay
              ? {
                  data: ["Processed", overlay.name],
                  top: 0,
                  textStyle: { color: c.axis },
                }
              : undefined,
            dataZoom,
            grid: {
              left: 56,
              right: overlay ? 56 : 20,
              top: overlay ? 34 : 16,
              bottom: gridBottom,
            },
            tooltip: {
              ...baseTooltip,
              trigger: "axis",
              axisPointer: compact
                ? { type: "line", lineStyle: { color: c.axis } }
                : {
                    type: "cross",
                    label: { backgroundColor: c.axis },
                    lineStyle: { color: c.axis },
                    crossStyle: { color: c.axis },
                  },
              valueFormatter: (v: unknown) =>
                typeof v === "number" ? fmt(v) : String(v),
            },
            xAxis: {
              type: "value",
              scale: true,
              name: AXIS_NAME,
              nameLocation: "middle",
              nameGap: 26,
              ...axisStyle,
            },
            yAxis: [
              {
                type: "value",
                scale: true,
                name: "Intensity",
                nameLocation: "middle",
                nameGap: 40,
                ...axisStyle,
              },
              {
                type: "value",
                scale: true,
                position: "right",
                show: Boolean(overlay),
                name: overlay ? overlay.name : "",
                ...axisStyle,
                splitLine: { show: false },
              },
            ],
            series,
          },
          { notMerge: true },
        );
        return;
      }

      // ---- N-series / customisable path. ----
      // Normalise both accepted shapes down to one `TraceSeries[]`.
      const opts = {
        stacked: dStacked ?? false,
        offset: dOffset ?? 0,
        normalize: dNormalize ?? "none",
        showLegend: dShowLegend ?? true,
        showGrid: dShowGrid ?? true,
        lineWidth: dLineWidth ?? 2,
      };

      const rawList: TraceSeries[] = multiSeries
        ? seriesProp!.slice()
        : [
            {
              name: overlay ? "Processed" : "Intensity",
              wavenumbers: wavenumbers ?? [],
              intensities: intensities ?? [],
            },
          ];
      if (!multiSeries && overlay) rawList.push(overlay);

      const legendVisible = opts.showLegend && rawList.length > 1;

      const built = rawList.map((s, i) => {
        // Copy + rescale for display only — caller arrays are never touched.
        const shaped =
          opts.normalize === "none"
            ? s.intensities
            : normalizeIntensities(s.intensities, opts.normalize);
        const shifted =
          opts.stacked && opts.offset
            ? shaped.map((y) => y + i * opts.offset)
            : shaped;
        return {
          name: s.name || `Series ${i + 1}`,
          color: c.palette[i % c.palette.length] ?? c.mean,
          data: zip(s.wavenumbers, shifted),
        };
      });

      const cropMin = Number.isFinite(dXMin) ? dXMin : undefined;
      const cropMax = Number.isFinite(dXMax) ? dXMax : undefined;
      // Keep the y-axis honest: only advertise "normalised" when it is.
      const yName =
        opts.normalize === "none"
          ? opts.stacked
            ? "Intensity (offset)"
            : "Intensity"
          : "Intensity (normalised)";
      const splitLine = { ...axisStyle.splitLine, show: opts.showGrid };

      const markLineOption =
        markers && markers.length
          ? {
              symbol: "none" as const,
              silent: true,
              animation: false,
              label: {
                show: true,
                formatter: (p: { data?: { label?: string } }) =>
                  p.data?.label ?? "",
                color: c.axis,
                fontSize: 10,
                position: "insideEndTop" as const,
              },
              lineStyle: { color: c.axis, type: "dashed" as const, width: 1, opacity: 0.55 },
              data: markers.map((m) => ({ xAxis: m.cm1, label: m.label })),
            }
          : undefined;

      const nSeries: Record<string, unknown>[] = built.map((b, i) => ({
        type: "line",
        name: b.name,
        data: b.data,
        showSymbol: false,
        sampling: "lttb",
        smooth: 0.15,
        lineStyle: { width: opts.lineWidth, color: b.color },
        itemStyle: { color: b.color },
        areaStyle: built.length === 1 ? areaFill : undefined,
        emphasis: { focus: "series" },
        // Guides hang off the first series only; repeating them per series
        // would stack identical lines and darken them.
        markLine: i === 0 ? markLineOption : undefined,
        z: 3,
      }));

      chart.setOption(
        {
          ...drawAnimation,
          textStyle: baseTextStyle,
          legend: legendVisible
            ? {
                type: "scroll",
                top: 0,
                data: built.map((b) => b.name),
                textStyle: { color: c.axis },
                pageIconColor: c.axis,
                pageIconInactiveColor: c.grid,
                pageTextStyle: { color: c.axis },
              }
            : undefined,
          dataZoom,
          grid: {
            left: 56,
            right: 20,
            top: legendVisible ? 34 : 16,
            bottom: gridBottom,
          },
          tooltip: {
            ...baseTooltip,
            trigger: "axis",
            axisPointer: compact
              ? { type: "line", lineStyle: { color: c.axis } }
              : {
                  type: "cross",
                  label: { backgroundColor: c.axis },
                  lineStyle: { color: c.axis },
                  crossStyle: { color: c.axis },
                },
            valueFormatter: (v: unknown) =>
              typeof v === "number" ? fmt(v) : String(v),
          },
          xAxis: {
            type: "value",
            scale: true,
            min: cropMin,
            max: cropMax,
            name: AXIS_NAME,
            nameLocation: "middle",
            nameGap: 26,
            ...axisStyle,
            splitLine,
          },
          yAxis: {
            type: "value",
            scale: true,
            name: yName,
            nameLocation: "middle",
            nameGap: 40,
            ...axisStyle,
            splitLine,
          },
          series: nSeries,
        },
        { notMerge: true },
      );
      return;
    }
  }, [
    loading,
    resolvedTheme,
    mode,
    grid,
    meanArr,
    stdArr,
    wavenumbers,
    intensities,
    overlay,
    seriesProp,
    markers,
    hasDisplay,
    dStacked,
    dOffset,
    dNormalize,
    dXMin,
    dXMax,
    dShowLegend,
    dShowGrid,
    dLineWidth,
    // Read inside the effect (`compact = height <= 200`) to pick the axis /
    // label density, so a height change must re-render the chart.
    height,
    // Toggling zoom changes the option shape (dataZoom + grid padding).
    // `zoomRange` deliberately is NOT a dependency — see `zoomRangeRef`.
    zoom,
  ]);

  // Push a controlled zoom window onto the live chart without rebuilding it.
  // `dispatchAction` is the cheap path; a full `setOption` here would redraw
  // the series on every wheel tick.
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || !zoom || !zoomRange || chart.isDisposed()) return;
    chart.dispatchAction({
      type: "dataZoom",
      dataZoomIndex: 0,
      start: zoomRange.start,
      end: zoomRange.end,
    });
  }, [zoom, zoomRange]);

  // Report user-driven zoom/pan back up so the parent's controls stay in sync
  // with what the chart is actually showing.
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || !zoom) return;
    const handler = () => {
      const opt = chart.getOption() as {
        dataZoom?: { start?: number; end?: number }[];
      };
      const first = opt.dataZoom?.[0];
      if (!first) return;
      onZoomChangeRef.current?.({
        start: first.start ?? 0,
        end: first.end ?? 100,
      });
    };
    chart.on("datazoom", handler);
    return () => {
      if (!chart.isDisposed()) chart.off("datazoom", handler);
    };
  }, [zoom]);

  return (
    <div
      ref={containerRef}
      style={{ width: "100%", height }}
      role="img"
      aria-label={
        ariaLabel ??
        (props.mode === "band"
          ? "Mean spectrum with standard-deviation band"
          : "Raman spectrum")
      }
    />
  );
}
