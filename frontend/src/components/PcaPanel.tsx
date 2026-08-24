import { useEffect, useMemo, useRef, useState } from 'react';
import * as echarts from 'echarts/core';
import { LineChart, ScatterChart } from 'echarts/charts';
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import type { PcaResult } from '../api/analysis';
import SpectrumChart from './SpectrumChart';

echarts.use([
  ScatterChart,
  LineChart,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  CanvasRenderer,
]);

const POINT_PALETTE = [
  '#2a78d6', '#d1690b', '#1f9e78', '#a24bc4',
  '#c23b52', '#7a8b1f', '#0f7fa8', '#8a5a2b',
];

function theme() {
  const styles = getComputedStyle(document.documentElement);
  const token = (name: string, fallback: string) =>
    styles.getPropertyValue(name).trim() || fallback;
  return {
    grid: token('--chart-grid', '#e1e0d9'),
    axisInk: token('--chart-axis-ink', '#898781'),
    surface: token('--chart-surface', '#fcfcfb'),
    text: token('--color-text', '#0b0b0b'),
  };
}

interface Props {
  result: PcaResult;
  /** Display label per spectrum, in the same order as `result.scores`. */
  labels: string[];
  /** Optional group per spectrum (e.g. material). Points sharing a group get
   * one color and one legend entry — which is what turns a scatter of dots
   * into a readable "do my classes separate?" answer. */
  groups?: string[];
}

/** PCA scores scatter + loadings.
 *
 * Both halves matter and they answer different questions. The scores plot
 * says *whether* samples separate; the loadings plot says *which bands*
 * drive that separation, which is the part that makes the result a
 * scientific claim rather than a picture. Showing scores alone is the most
 * common way a PCA figure ends up uninterpretable. */
export default function PcaPanel({ result, labels, groups }: Props) {
  const scoresRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);
  const [xComponent, setXComponent] = useState(0);
  const [yComponent, setYComponent] = useState(1);
  const [loadingIndex, setLoadingIndex] = useState(0);

  const variance = result.explained_variance_ratio;
  const componentOptions = Array.from({ length: result.n_components }, (_, i) => i);

  const grouped = useMemo(() => {
    const byGroup = new Map<string, Array<{ value: [number, number]; name: string }>>();
    result.scores.forEach((row, index) => {
      const key = groups?.[index] ?? 'Spectra';
      if (!byGroup.has(key)) byGroup.set(key, []);
      byGroup.get(key)!.push({
        value: [row[xComponent] ?? 0, row[yComponent] ?? 0],
        name: labels[index] ?? `Spectrum ${index + 1}`,
      });
    });
    return byGroup;
  }, [result.scores, groups, labels, xComponent, yComponent]);

  useEffect(() => {
    if (!scoresRef.current) return;
    const chart = echarts.init(scoresRef.current);
    chartRef.current = chart;
    const onResize = () => chart.resize();
    window.addEventListener('resize', onResize);
    return () => {
      window.removeEventListener('resize', onResize);
      chart.dispose();
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const t = theme();
    const axisStyle = {
      nameTextStyle: { color: t.axisInk },
      axisLabel: { color: t.axisInk },
      axisLine: { lineStyle: { color: t.grid } },
      splitLine: { lineStyle: { color: t.grid } },
    };

    const pct = (i: number) =>
      variance[i] !== undefined ? ` (${(variance[i] * 100).toFixed(1)}%)` : '';

    chart.setOption(
      {
        textStyle: { fontFamily: 'system-ui, -apple-system, "Segoe UI", sans-serif' },
        tooltip: {
          trigger: 'item',
          formatter: (p: { name: string; value: [number, number] }) =>
            `${p.name}<br/>PC${xComponent + 1}: ${p.value[0].toFixed(2)}<br/>PC${
              yComponent + 1
            }: ${p.value[1].toFixed(2)}`,
          backgroundColor: t.surface,
          borderColor: t.grid,
          borderRadius: 10,
          textStyle: { color: t.text },
        },
        legend:
          grouped.size > 1
            ? { data: [...grouped.keys()], top: 0, textStyle: { color: t.axisInk } }
            : { show: false },
        grid: { left: 70, right: 30, top: grouped.size > 1 ? 44 : 24, bottom: 56 },
        xAxis: {
          type: 'value',
          name: `PC${xComponent + 1}${pct(xComponent)}`,
          nameLocation: 'middle',
          nameGap: 32,
          scale: true,
          ...axisStyle,
        },
        yAxis: {
          type: 'value',
          name: `PC${yComponent + 1}${pct(yComponent)}`,
          nameLocation: 'middle',
          nameGap: 50,
          scale: true,
          ...axisStyle,
        },
        series: [...grouped.entries()].map(([group, points], index) => ({
          type: 'scatter',
          name: group,
          data: points,
          symbolSize: 14,
          itemStyle: {
            color: POINT_PALETTE[index % POINT_PALETTE.length],
            opacity: 0.85,
            borderColor: t.surface,
            borderWidth: 1.5,
          },
        })),
      },
      { replaceMerge: ['series', 'legend'] },
    );
  }, [grouped, xComponent, yComponent, variance]);

  const totalExplained = variance
    .slice(0, Math.max(xComponent, yComponent) + 1)
    .reduce((a, b) => a + b, 0);

  return (
    <div className="pca">
      <div className="pca__controls">
        <label>
          X axis
          <select value={xComponent} onChange={(e) => setXComponent(Number(e.target.value))}>
            {componentOptions.map((i) => (
              <option key={i} value={i}>
                PC{i + 1}
              </option>
            ))}
          </select>
        </label>
        <label>
          Y axis
          <select value={yComponent} onChange={(e) => setYComponent(Number(e.target.value))}>
            {componentOptions.map((i) => (
              <option key={i} value={i}>
                PC{i + 1}
              </option>
            ))}
          </select>
        </label>
        <span className="hint">
          {result.n_spectra} spectra · PC1–PC{Math.max(xComponent, yComponent) + 1} explain{' '}
          {(totalExplained * 100).toFixed(1)}% of the variance
        </span>
      </div>

      <div ref={scoresRef} style={{ width: '100%', height: '360px' }} role="img"
        aria-label="PCA scores scatter plot" />

      <div className="pca__loadings">
        <div className="pca__controls">
          <label>
            Loading
            <select
              value={loadingIndex}
              onChange={(e) => setLoadingIndex(Number(e.target.value))}
            >
              {componentOptions.map((i) => (
                <option key={i} value={i}>
                  PC{i + 1}
                </option>
              ))}
            </select>
          </label>
          <span className="hint">
            Which bands drive PC{loadingIndex + 1}. Peaks here are the wavenumbers that
            separate your samples; a flat region contributes nothing.
          </span>
        </div>
        <SpectrumChart
          height={220}
          series={[
            {
              name: `PC${loadingIndex + 1} loading`,
              wavenumbers: result.wavenumbers,
              intensities: result.loadings[loadingIndex] ?? [],
            },
          ]}
        />
      </div>
    </div>
  );
}
