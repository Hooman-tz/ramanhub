// Display-only normalization for multi-spectrum plots.
//
// IMPORTANT: nothing here touches stored data. These transforms are applied
// to the arrays on their way into a chart, so an overlay is readable; the
// spectrum's raw file and its processing ledger are untouched. If you want a
// normalization to be part of the record — replayable, exported, cited —
// add it as a ledger step in the pipeline builder instead. That distinction
// is the whole reason this file is separate from the processing API.
//
// Why a display normalization is needed at all: overlaying spectra as
// stored compares BRIGHTNESS, not band structure. Two acquisitions of the
// same material at different laser powers or integration times can differ
// by orders of magnitude, so the larger one flattens the smaller into the
// baseline and the plot says nothing about chemistry.

export type DisplayNormalization = 'none' | 'snv' | 'minmax' | 'area';

export const NORMALIZATION_OPTIONS: Array<{
  value: DisplayNormalization;
  label: string;
  hint: string;
}> = [
  {
    value: 'snv',
    label: 'SNV',
    hint: 'Standard normal variate — centres each spectrum and divides by its own '
      + 'standard deviation. The default for comparing band structure across '
      + 'acquisitions with different intensity scales.',
  },
  {
    value: 'minmax',
    label: 'Min–max',
    hint: 'Scales each spectrum to 0–1. Intuitive, but a single cosmic-ray spike '
      + 'sets the maximum and squashes everything else.',
  },
  {
    value: 'area',
    label: 'Area',
    hint: 'Scales each spectrum to unit area. Appropriate when total scattered '
      + 'intensity is the meaningful quantity.',
  },
  {
    value: 'none',
    label: 'As stored',
    hint: 'Raw intensities, exactly as held. Correct when the absolute scale is '
      + 'the point — and misleading when it is not.',
  },
];

function mean(values: number[]): number {
  if (values.length === 0) return 0;
  let total = 0;
  for (const value of values) total += value;
  return total / values.length;
}

/** Standard normal variate: (x - mean) / standard deviation, per spectrum.
 *
 * Uses the population standard deviation (divide by N), which is the
 * convention in the chemometrics literature this is named for — matching
 * the backend's `raman.snv` ledger step, so a display preview and a
 * committed pipeline step produce the same shape rather than subtly
 * different ones. */
export function snv(intensities: number[]): number[] {
  if (intensities.length === 0) return intensities;
  const mu = mean(intensities);
  let sumSquares = 0;
  for (const value of intensities) sumSquares += (value - mu) ** 2;
  const sigma = Math.sqrt(sumSquares / intensities.length);
  // A perfectly flat spectrum has zero variance; scaling it would divide by
  // zero. Centring alone is the sane degenerate case.
  if (sigma === 0) return intensities.map((value) => value - mu);
  return intensities.map((value) => (value - mu) / sigma);
}

export function minmax(intensities: number[]): number[] {
  if (intensities.length === 0) return intensities;
  let lo = Infinity;
  let hi = -Infinity;
  for (const value of intensities) {
    if (value < lo) lo = value;
    if (value > hi) hi = value;
  }
  const range = hi - lo;
  if (range === 0) return intensities.map(() => 0);
  return intensities.map((value) => (value - lo) / range);
}

/** Unit area, using the trapezoid rule over the actual wavenumber axis.
 *
 * The axis matters: summing intensities alone silently assumes a uniform
 * grid, and spectra from different instruments rarely share one. */
export function area(wavenumbers: number[], intensities: number[]): number[] {
  if (intensities.length < 2) return intensities;
  let total = 0;
  for (let i = 1; i < intensities.length; i += 1) {
    const width = Math.abs(wavenumbers[i] - wavenumbers[i - 1]);
    total += ((intensities[i] + intensities[i - 1]) / 2) * width;
  }
  if (total === 0) return intensities;
  return intensities.map((value) => value / total);
}

export function applyDisplayNormalization(
  wavenumbers: number[],
  intensities: number[],
  mode: DisplayNormalization,
): number[] {
  switch (mode) {
    case 'snv':
      return snv(intensities);
    case 'minmax':
      return minmax(intensities);
    case 'area':
      return area(wavenumbers, intensities);
    default:
      return intensities;
  }
}

/** Axis label reflecting the applied transform, so a reader can't mistake
 * normalized values for measured counts. */
export function intensityAxisLabel(mode: DisplayNormalization): string {
  switch (mode) {
    case 'snv':
      return 'Intensity (SNV)';
    case 'minmax':
      return 'Intensity (0–1)';
    case 'area':
      return 'Intensity (unit area)';
    default:
      return 'Intensity';
  }
}
