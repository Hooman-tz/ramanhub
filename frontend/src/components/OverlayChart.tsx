import { useState } from 'react';
import SpectrumChart, { type PeakMarker, type Series } from './SpectrumChart';
import {
  applyDisplayNormalization,
  intensityAxisLabel,
  NORMALIZATION_OPTIONS,
  type DisplayNormalization,
} from '../lib/normalize';

interface Props {
  series: Series[];
  height?: number;
  zoomable?: boolean;
  peaks?: PeakMarker[];
  /** Starting scaling. SNV by default wherever spectra are overlaid, since
   * as-stored intensities compare brightness rather than band structure. */
  defaultNormalization?: DisplayNormalization;
  /** Extra note rendered under the chart, above the shared disclaimer. */
  children?: React.ReactNode;
}

/** A multi-spectrum overlay with its scaling control attached.
 *
 * One component rather than a control re-implemented per page: every place
 * that overlays spectra gets the same options, the same SNV default, the
 * same relabelled axis, and the same "display-only" disclaimer. Hardcoding
 * the scaling at any one call site would take the choice away from the
 * person who actually knows whether absolute intensity matters for their
 * samples. */
export default function OverlayChart({
  series,
  height = 460,
  zoomable = true,
  peaks,
  defaultNormalization = 'snv',
  children,
}: Props) {
  const [normalization, setNormalization] = useState<DisplayNormalization>(
    defaultNormalization,
  );

  const scaled = series.map((s) => ({
    ...s,
    intensities: applyDisplayNormalization(s.wavenumbers, s.intensities, normalization),
  }));

  const active = NORMALIZATION_OPTIONS.find((o) => o.value === normalization);

  return (
    <div className="overlay-chart">
      <div className="chart-panel__controls">
        <label>
          <span>Scaling</span>
          <select
            value={normalization}
            onChange={(e) => setNormalization(e.target.value as DisplayNormalization)}
          >
            {NORMALIZATION_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <p className="hint">{active?.hint}</p>
      </div>

      <SpectrumChart
        flush
        zoomable={zoomable}
        height={height}
        peaks={peaks}
        yAxisLabel={intensityAxisLabel(normalization)}
        series={scaled}
      />

      <p className="hint chart-panel__foot">
        {children}
        {children ? ' ' : null}
        Scaling is applied for display only — the stored data and each spectrum's
        processing ledger are untouched. To make a normalization part of the record, add
        it as a pipeline step on the spectrum itself.
      </p>
    </div>
  );
}
