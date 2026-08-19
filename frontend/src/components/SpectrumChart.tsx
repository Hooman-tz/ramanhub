import { useEffect, useRef } from 'react';
import * as echarts from 'echarts';

interface Props {
  wavenumbers: number[];
  intensities: number[];
  loading?: boolean;
}

/** Single-series Raman spectrum line chart, built directly on the core
 * `echarts` package (not `echarts-for-react`) via the standard vanilla-JS
 * init/dispose-on-a-div-ref pattern. */
export default function SpectrumChart({ wavenumbers, intensities, loading }: Props) {
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

    chart.setOption({
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        valueFormatter: (value: unknown) => (typeof value === 'number' ? value.toFixed(2) : String(value)),
      },
      grid: { left: 60, right: 30, top: 30, bottom: 50 },
      xAxis: {
        type: 'value',
        name: 'Raman shift (cm⁻¹)',
        nameLocation: 'middle',
        nameGap: 30,
        scale: true,
      },
      yAxis: {
        type: 'value',
        name: 'Intensity',
        nameLocation: 'middle',
        nameGap: 45,
        scale: true,
      },
      series: [
        {
          type: 'line',
          data,
          showSymbol: false,
          smooth: false,
          sampling: 'lttb',
          lineStyle: { width: 1.5 },
        },
      ],
    });
  }, [wavenumbers, intensities, loading]);

  return (
    <div
      ref={containerRef}
      style={{ width: '100%', height: '400px' }}
      role="img"
      aria-label="Raman spectrum chart"
    />
  );
}
