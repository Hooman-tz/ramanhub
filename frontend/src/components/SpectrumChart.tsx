import { useEffect, useMemo, useRef } from 'react';
// Tree-shaken ECharts: registering only the line chart and the components
// this app uses, rather than `import * as echarts from 'echarts'`, which
// pulls every chart type into the bundle. ECharts was chosen over Plotly for
// mobile weight in the first place, so importing all of it would give the
// download cost back.
import * as echarts from 'echarts/core';
import { LineChart } from 'echarts/charts';
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkPointComponent,
  TooltipComponent,
} from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';

echarts.use([
  LineChart,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  MarkPointComponent,
  DataZoomComponent,
  CanvasRenderer,
]);

/** Categorical series palette, from the validated dataviz reference set.
 *
 * Ordered so the first colors are the most separable — a two-series compare
 * (the common case) gets blue vs. orange, which stays distinguishable under
 * every common form of color-vision deficiency. Series identity is never
 * carried by color alone: the legend is always shown once there's more than
 * one series, and the tooltip names each line. */
const SERIES_PALETTE = [
  '#2a78d6', // blue
  '#d1690b', // orange
  '#1f9e78', // teal-green
  '#a24bc4', // purple
  '#c23b52', // crimson
  '#7a8b1f', // olive
  '#0f7fa8', // cyan-blue
  '#8a5a2b', // brown
];

/** Chart colors resolved from the design tokens at render time — ECharts
 * paints to canvas, so it can't read CSS custom properties itself.
 *
 * Palette-validator note: the raw overlay deliberately uses the muted ink
 * `#898781`, which fails the validator's chroma floor ("reads gray") — by
 * design. The overlay is a recessive *reference layer*, not a competing
 * series, and its identity is carried by secondary encoding (dashed line,
 * always-on legend, its own labeled axis). */
function chartTheme() {
  const styles = getComputedStyle(document.documentElement);
  const token = (name: string, fallback: string) =>
    styles.getPropertyValue(name).trim() || fallback;
  return {
    series1: token('--chart-series-1', '#2a78d6'),
    overlay: token('--chart-series-overlay', '#898781'),
    grid: token('--chart-grid', '#e1e0d9'),
    axisInk: token('--chart-axis-ink', '#898781'),
    surface: token('--chart-surface', '#fcfcfb'),
    text: token('--color-text', '#0b0b0b'),
  };
}

export interface Series {
  name: string;
  wavenumbers: number[];
  intensities: number[];
  /** Overrides the palette slot. */
  color?: string;
  /** Recessive reference styling: dashed, thinner, drawn behind, and given
   * its own right-hand axis. */
  reference?: boolean;
}

export interface PeakMarker {
  wavenumber: number;
  intensity: number;
}

interface Props {
  /** Preferred API: any number of series. */
  series?: Series[];
  /** Single-series shorthand, kept because most callers show one spectrum. */
  wavenumbers?: number[];
  intensities?: number[];
  name?: string;
  /** A recessive second line (the raw spectrum behind the processed one). */
  overlay?: Series;
  loading?: boolean;
  /** Marks detected bands with a labelled pin on the first series. */
  peaks?: PeakMarker[];
  height?: number;
  /** Adds a brush-and-scroll zoom along the wavenumber axis. Off by default
   * because it adds chrome that a small preview chart doesn't need. */
  zoomable?: boolean;
  /** Tightens the internal grid margins for a chart that sits flush inside
   * a card. ECharts reserves space for axis labels independently of CSS
   * padding, so a card's own padding plus the default grid inset reads as a
   * large empty frame around the plot. */
  flush?: boolean;
  /** Overrides the y-axis name — used to state a display normalization
   * ("Intensity (SNV)") so normalized values can't be mistaken for counts. */
  yAxisLabel?: string;
}

/** Raman spectrum line chart, built directly on the core `echarts` package
 * (not `echarts-for-react`) via the standard vanilla-JS
 * init/dispose-on-a-div-ref pattern. */
export default function SpectrumChart({
  series,
  wavenumbers,
  intensities,
  name = 'Processed',
  overlay,
  loading,
  peaks,
  height = 400,
  zoomable = false,
  flush = false,
  yAxisLabel = 'Intensity',
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);

  // Normalize both call shapes to one list, so the render path below never
  // branches on which API the caller used.
  const resolved = useMemo<Series[]>(() => {
    if (series && series.length > 0) return series;
    const out: Series[] = [];
    if (wavenumbers && intensities) {
      out.push({ name, wavenumbers, intensities });
    }
    if (overlay) out.push({ ...overlay, reference: true });
    return out;
  }, [series, wavenumbers, intensities, name, overlay]);

  // Init once, dispose on unmount.
  useEffect(() => {
    if (!containerRef.current) return;
    const chart = echarts.init(containerRef.current);
    chartRef.current = chart;

    const handleResize = () => chart.resize();
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.dispose();
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;

    if (loading) {
      chart.showLoading();
      return;
    }
    chart.hideLoading();

    const theme = chartTheme();
    const hasReference = resolved.some((s) => s.reference);
    const showLegend = resolved.length > 1;

    const echartsSeries = resolved.map((s, index) => {
      // Raw and processed intensities routinely differ by orders of
      // magnitude (normalization alone takes counts to 0-1), so a reference
      // series gets its own right-hand axis. Sharing one would flatten
      // whichever series is smaller into the baseline.
      const color = s.color ?? (s.reference ? theme.overlay : SERIES_PALETTE[index % SERIES_PALETTE.length]);
      return {
        type: 'line',
        name: s.name,
        data: s.wavenumbers.map((wn, i) => [wn, s.intensities[i]]),
        showSymbol: false,
        smooth: false,
        sampling: 'lttb',
        color,
        lineStyle: s.reference
          ? { width: 1.25, opacity: 0.7, type: 'dashed' }
          : { width: 1.8 },
        yAxisIndex: s.reference ? 1 : 0,
        z: s.reference ? 1 : 3,
        ...(index === 0 && peaks && peaks.length > 0
          ? {
              markPoint: {
                symbol: 'pin',
                symbolSize: 34,
                itemStyle: { color, opacity: 0.85 },
                label: {
                  formatter: (p: { data: { coord: [number, number] } }) =>
                    String(Math.round(p.data.coord[0])),
                  fontSize: 9,
                  color: '#fff',
                },
                data: peaks.map((peak) => ({
                  coord: [peak.wavenumber, peak.intensity],
                  value: peak.wavenumber,
                })),
              },
            }
          : {}),
      };
    });

    const axisStyle = {
      nameTextStyle: { color: theme.axisInk },
      axisLabel: { color: theme.axisInk },
      axisLine: { lineStyle: { color: theme.grid } },
      splitLine: { lineStyle: { color: theme.grid } },
    };

    chart.setOption(
      {
        textStyle: { fontFamily: 'system-ui, -apple-system, "Segoe UI", sans-serif' },
        tooltip: {
          trigger: 'axis',
          axisPointer: { type: 'cross', label: { backgroundColor: theme.axisInk } },
          valueFormatter: (value: unknown) =>
            typeof value === 'number' ? value.toFixed(2) : String(value),
          backgroundColor: theme.surface,
          borderColor: theme.grid,
          borderRadius: 10,
          padding: [8, 12],
          textStyle: { color: theme.text },
          extraCssText:
            'backdrop-filter: blur(8px); box-shadow: 0 8px 24px -6px rgba(0,0,0,0.18);',
        },
        legend: showLegend
          ? {
              type: 'scroll',
              data: resolved.map((s) => s.name),
              top: 0,
              textStyle: { color: theme.axisInk },
            }
          : { show: false },
        grid: {
          // `containLabel` lets ECharts measure the axis labels and reserve
          // exactly what they need, instead of the fixed inset guessed here.
          // With it on, the remaining values are a small breathing margin
          // rather than a label allowance, which is what closes the gap
          // between the plot and its card.
          containLabel: true,
          left: flush ? 8 : 24,
          right: flush ? (hasReference ? 40 : 8) : 24,
          top: showLegend ? 36 : flush ? 12 : 24,
          bottom: zoomable ? 54 : flush ? 12 : 24,
        },
        xAxis: {
          type: 'value',
          name: 'Raman shift (cm⁻¹)',
          scale: true,
          // NOTE: ...axisStyle must come BEFORE the name overrides below —
          // it carries its own nameTextStyle, and spreading it afterwards
          // would silently discard them.
          ...axisStyle,
          // Flush charts label the axes at their far END, horizontally,
          // rather than rotated in the middle. `containLabel` reserves room
          // for tick labels but NOT for an axis name, so a middle-positioned
          // name would be pushed off-canvas and clipped at these margins —
          // and an end label reads more easily besides.
          nameLocation: flush ? 'end' : 'middle',
          nameGap: flush ? 8 : 30,
          nameTextStyle: {
            color: theme.axisInk,
            ...(flush ? { align: 'right', verticalAlign: 'top' } : {}),
          },
        },
        yAxis: [
          {
            type: 'value',
            scale: true,
            ...axisStyle,
            name: yAxisLabel,
            nameLocation: flush ? 'end' : 'middle',
            nameGap: flush ? 10 : 52,
            nameTextStyle: {
              color: theme.axisInk,
              ...(flush ? { align: 'left' } : {}),
            },
          },
          {
            type: 'value',
            name: hasReference ? 'Raw' : '',
            position: 'right',
            scale: true,
            show: hasReference,
            ...axisStyle,
            splitLine: { show: false },
          },
        ],
        dataZoom: zoomable
          ? [
              { type: 'inside', xAxisIndex: 0 },
              { type: 'slider', xAxisIndex: 0, bottom: 12, height: 20 },
            ]
          : [],
        series: echartsSeries,
      },
      // Replace rather than merge: without this, removing a series from the
      // compare set leaves its line painted on the chart forever, because
      // ECharts merges by index and never drops the surplus.
      { replaceMerge: ['series', 'legend', 'dataZoom'] },
    );
  }, [resolved, loading, peaks, zoomable, flush, yAxisLabel]);

  return (
    <div
      ref={containerRef}
      style={{ width: '100%', height: `${height}px` }}
      role="img"
      aria-label="Raman spectrum chart"
    />
  );
}
