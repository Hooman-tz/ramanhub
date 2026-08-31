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
  };
}

const AXIS_NAME = "Raman shift (cm⁻¹)";

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
    if (!containerRef.current) return;
    const chart = echarts.init(containerRef.current);
    chartRef.current = chart;

    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(containerRef.current);

    return () => {
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
      splitLine: { lineStyle: { color: c.grid } },
    };
    const baseTooltip = {
      backgroundColor: "rgba(255,255,255,0.92)",
      borderColor: c.grid,
      borderWidth: 1,
      borderRadius: 8,
      padding: [6, 10],
      textStyle: { color: "#0b0b0b", fontSize: 12 },
      extraCssText: "backdrop-filter: blur(6px);",
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
          animation: false,
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
              lineStyle: { width: 2, color: c.mean },
              itemStyle: { color: c.mean },
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
          lineStyle: { width: 2, color: c.mean },
          itemStyle: { color: c.mean },
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
          animation: false,
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
            axisPointer: {
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
