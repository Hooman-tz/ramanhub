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
        lineStyle: { width: 1.5 },
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
        lineStyle: { width: 1, opacity: 0.5, type: 'dashed' },
        yAxisIndex: 1,
        z: 1,
      });
    }

    chart.setOption({
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        valueFormatter: (value: unknown) => (typeof value === 'number' ? value.toFixed(2) : String(value)),
      },
      legend: overlay ? { data: [name, overlay.name], top: 0 } : undefined,
      grid: { left: 60, right: overlay ? 60 : 30, top: overlay ? 50 : 30, bottom: 50 },
      xAxis: {
        type: 'value',
        name: 'Raman shift (cm⁻¹)',
        nameLocation: 'middle',
        nameGap: 30,
        scale: true,
      },
      yAxis: [
        {
          type: 'value',
          name: 'Intensity',
          nameLocation: 'middle',
          nameGap: 45,
          scale: true,
        },
        {
          type: 'value',
          name: overlay ? overlay.name : '',
          position: 'right',
          scale: true,
          show: Boolean(overlay),
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
