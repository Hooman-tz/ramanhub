"use client";

import { useEffect, useRef } from "react";
// Tree-shaken ECharts: only the line chart + the handful of components these
// two chart modes use, rather than `import * as echarts from "echarts"` which
// pulls every chart type into the web bundle.
import { LineChart } from "echarts/charts";
import {
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
  CanvasRenderer,
]);

interface TraceSeries {
  name: string;
  wavenumbers: number[];
  intensities: number[];
}

type SpectrumChartProps = {
  /** Fixed pixel height for the chart canvas. */
  height?: number;
  /** Show ECharts' built-in loading spinner. */
  loading?: boolean;
  /** Accessible label — the chart canvas gets `role="img"`. */
  ariaLabel?: string;
} & (
  | {
      mode: "trace";
      wavenumbers: number[];
      intensities: number[];
      /**
       * A second line drawn on its own right-hand axis — raw vs processed
       * intensities routinely differ by orders of magnitude, so sharing one
       * axis would flatten the smaller series into the baseline.
       */
      overlay?: TraceSeries;
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
  const { height = 320, loading = false, ariaLabel } = props;
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);
  const { resolvedTheme } = useTheme();

  // Narrowed, referentially-stable data handles (the arrays come straight
  // from React Query cache) so the draw effect only re-runs on real change.
  const mode = props.mode;
  const grid = props.mode === "band" ? props.grid : undefined;
  const meanArr = props.mode === "band" ? props.mean : undefined;
  const stdArr = props.mode === "band" ? props.std : undefined;
  const wavenumbers = props.mode === "trace" ? props.wavenumbers : undefined;
  const intensities = props.mode === "trace" ? props.intensities : undefined;
  const overlay = props.mode === "trace" ? props.overlay : undefined;

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
    const compact = height <= 200;

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
          grid: { left: 56, right: 20, top: 16, bottom: 44 },
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

    if (mode === "trace" && wavenumbers && intensities) {
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
          grid: {
            left: 56,
            right: overlay ? 56 : 20,
            top: overlay ? 34 : 16,
            bottom: 44,
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
  ]);

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
