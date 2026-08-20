import { useEffect, useRef } from 'react';
// Tree-shaken ECharts: registering only the line chart and the four
// components this app uses, rather than `import * as echarts from 'echarts'`,
// which pulls every chart type into the bundle. ECharts was chosen over
// Plotly for mobile weight in the first place, so importing all of it would
// give the download cost back.
import * as echarts from 'echarts/core';
import { LineChart } from 'echarts/charts';
import {
  GridComponent,
  LegendComponent,
  TooltipComponent,
} from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';

echarts.use([LineChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer]);

/** Chart colors resolved from the design tokens at render time — ECharts
 * paints to canvas, so it can't read CSS custom properties itself. The
 * `--chart-*` tokens are plain hexes from the validated dataviz reference
 * palette (series-1 blue per mode; grid/axis inks).
 *
 * Palette-validator note: the raw overlay deliberately uses the muted ink
 * `#898781`, which fails the validator's chroma floor ("reads gray") — by
 * design. The overlay is a recessive *reference layer*, not a competing
 * series, and its identity is carried by secondary encoding (dashed line,
 * always-on legend, its own labeled axis). CVD and normal-vision separation
 * against the blue both pass with wide margins (ΔE 15.9 / 17.8 light,
 * 15.9 / 17.0 dark). */
function chartTheme() {
  const styles = getComputedStyle(document.documentElement);
  const token = (name: string, fallback: string) =>
    styles.getPropertyValue(name).trim() || fallback;
  return {
    series1: token('--chart-series-1', '#2a78d6'),
    overlay: token('--chart-series-overlay', '#898781'),
    grid: token('--chart-grid', '#e1e0d9'),
    axisInk: token('--chart-axis-ink', '#898781'),
  };
}

interface Series {
  name: string;
  wavenumbers: number[];
  intensities: number[];
}

interface Props {
  wavenumbers: number[];
  intensities: number[];
  loading?: boolean;
  /** Optional extra series drawn behind the main one — used to show the raw
   * spectrum under the processed result while a pipeline is being built.
   * Its own wavenumber array is kept rather than reusing the main one,
   * since cropping and resampling change the axis. */
  overlay?: Series;
  /** Label for the main series; only shown when there's an overlay to
   * distinguish it from. */
  name?: string;
}

/** Raman spectrum line chart, built directly on the core `echarts` package
 * (not `echarts-for-react`) via the standard vanilla-JS
 * init/dispose-on-a-div-ref pattern. */
export default function SpectrumChart({
  wavenumbers,
  intensities,
  loading,
  overlay,
  name = 'Processed',
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);

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

  // Update data/loading state whenever it changes.
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;

    if (loading) {
      chart.showLoading();
      return;
    }
    chart.hideLoading();

    const data: [number, number][] = wavenumbers.map((wn, i) => [wn, intensities[i]]);
    const theme = chartTheme();

    // Raw and processed intensities routinely differ by orders of magnitude
    // (normalization alone takes counts to 0-1), so the overlay gets its own
    // right-hand axis. Sharing one would flatten whichever series is
    // smaller into the baseline and make the comparison useless.
    const series: Record<string, unknown>[] = [
      {
        type: 'line',
        name,
        data,
        showSymbol: false,
        smooth: false,
        sampling: 'lttb',
        color: theme.series1,
        lineStyle: { width: 2 },
        yAxisIndex: 0,
        z: 3,
      },
    ];
    if (overlay) {
      series.push({
        type: 'line',
        name: overlay.name,
        data: overlay.wavenumbers.map((wn, i) => [wn, overlay.intensities[i]]),
        showSymbol: false,
        smooth: false,
        sampling: 'lttb',
        color: theme.overlay,
        lineStyle: { width: 1.25, opacity: 0.7, type: 'dashed' },
        yAxisIndex: 1,
        z: 1,
      });
    }

    const axisStyle = {
      nameTextStyle: { color: theme.axisInk },
      axisLabel: { color: theme.axisInk },
      axisLine: { lineStyle: { color: theme.grid } },
      splitLine: { lineStyle: { color: theme.grid } },
    };

    chart.setOption({
      textStyle: { fontFamily: 'system-ui, -apple-system, "Segoe UI", sans-serif' },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross', label: { backgroundColor: theme.axisInk } },
        valueFormatter: (value: unknown) => (typeof value === 'number' ? value.toFixed(2) : String(value)),
        // Glass-adjacent tooltip: translucent, blurred, rounded like every
        // other elevated surface in the app.
        backgroundColor: 'rgba(252, 252, 251, 0.85)',
        borderColor: theme.grid,
        borderRadius: 10,
        padding: [8, 12],
        textStyle: { color: '#0b0b0b' },
        extraCssText: 'backdrop-filter: blur(8px); box-shadow: 0 8px 24px -6px rgba(0,0,0,0.18);',
      },
      legend: overlay
        ? { data: [name, overlay.name], top: 0, textStyle: { color: theme.axisInk } }
        : undefined,
      grid: { left: 60, right: overlay ? 60 : 30, top: overlay ? 50 : 30, bottom: 50 },
      xAxis: {
        type: 'value',
        name: 'Raman shift (cm⁻¹)',
        nameLocation: 'middle',
        nameGap: 30,
        scale: true,
        ...axisStyle,
      },
      yAxis: [
        {
          type: 'value',
          name: 'Intensity',
          nameLocation: 'middle',
          nameGap: 45,
          scale: true,
          ...axisStyle,
        },
        {
          type: 'value',
          name: overlay ? overlay.name : '',
          position: 'right',
          scale: true,
          show: Boolean(overlay),
          ...axisStyle,
          splitLine: { show: false },
        },
      ],
      series,
    });
  }, [wavenumbers, intensities, loading, overlay, name]);

  return (
    <div
      ref={containerRef}
      style={{ width: '100%', height: '400px' }}
      role="img"
      aria-label="Raman spectrum chart"
    />
  );
}
