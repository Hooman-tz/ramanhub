/**
 * Client-side peak detection — a mirror of `backend/app/processing/peaks.py`.
 *
 * ## What this is for, and what it is not for
 *
 * The Library tab shows a spectrum's bands the instant it is selected, before
 * any network request, using the buffer the chart already holds. That preview
 * is **advisory**: it is what the user sees and can adjust.
 *
 * `POST /v1/library/match` always recomputes peaks server-side and indexes
 * against those. So if this port and the Python one ever disagree, the
 * consequence is a slightly different set of markers before the user presses
 * Match — never a different match result. That is deliberate: two independent
 * implementations of the same maths will drift, and the design puts the drift
 * somewhere harmless rather than pretending it cannot happen.
 *
 * `PEAK_DETECTOR_VERSION` names the Python module this mirrors. It is not
 * checked against a catalog endpoint the way `PREVIEW_ALGORITHM_VERSIONS` is —
 * there is no peaks catalog — so it exists to make drift *legible*, not to
 * block on it.
 */

import type { BufferedSpectrum } from "./index";
import type { Float64Buffer } from "./numeric";
import { mad, median, percentile } from "./numeric";

/** The `backend/app/processing/peaks.py` version this port mirrors. */
export const PEAK_DETECTOR_VERSION = "raman-peaks-1";

export const PEAK_BIN_WIDTH_CM1 = 4;
const DEFAULT_MIN_PROMINENCE_SIGMA = 6;
const DEFAULT_MIN_DISTANCE_CM1 = 6;
const DEFAULT_MAX_PEAKS = 20;
const DEFAULT_BASELINE_WINDOW = 101;

export interface DetectedPeak {
  cm1: number;
  /** Baseline-subtracted. */
  height: number;
  /** Height relative to the strongest band, in (0, 1]. */
  relHeight: number;
  prominence: number;
  snr: number;
}

export interface PeakProfile {
  peaks: DetectedPeak[];
  primaryPeakCm1: number | null;
  peakToBackground: number;
  baselineLevel: number;
  noiseSigma: number;
}

export interface PeakOptions {
  minProminenceSigma?: number;
  minDistanceCm1?: number;
  maxPeaks?: number;
  baselineWindow?: number;
}

export class PeakError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PeakError";
  }
}

/**
 * A rolling low percentile — the slow-varying floor under the bands.
 *
 * Raman spectra routinely sit on a fluorescence ramp taller than the bands
 * themselves, so ranking raw intensity would return the top of the ramp rather
 * than the strongest band. A percentile rather than a minimum, because a
 * rolling minimum latches onto negative noise excursions.
 */
function estimateBaseline(y: Float64Buffer, window: number): Float64Array {
  const n = y.length;
  const out = new Float64Array(n);
  if (n === 0) return out;

  let w = Math.max(3, Math.min(window | 1, n % 2 ? n : n - 1));
  if (w > n) w = n % 2 ? n : n - 1;
  const half = Math.floor(w / 2);
  const scratch = new Float64Array(w);

  for (let i = 0; i < n; i += 1) {
    for (let k = 0; k < w; k += 1) {
      // Edge padding, matching numpy's `mode="edge"`.
      const idx = Math.min(n - 1, Math.max(0, i - half + k));
      scratch[k] = y[idx]!;
    }
    out[i] = percentile(scratch, 10);
  }
  return out;
}

/**
 * Robust sigma via the median absolute deviation.
 *
 * Not the standard deviation: over a spectrum that is dominated by the peaks,
 * which would scale the detection threshold with the very thing being detected.
 */
function estimateNoise(residual: Float64Array): number {
  if (residual.length === 0) return 0;
  const sigma = 1.4826 * mad(residual);
  if (sigma > 0) return sigma;
  // A flat or heavily quantized trace has zero MAD.
  const m = median(residual);
  let acc = 0;
  for (let i = 0; i < residual.length; i += 1) acc += (residual[i]! - m) ** 2;
  return Math.sqrt(acc / residual.length);
}

/**
 * Sub-sample peak position by fitting a parabola to three points.
 *
 * Without this every position is quantized to the sampling grid, which can be
 * coarser than the 4 cm-1 bin width — so a band would land in one bucket or
 * its neighbour depending only on where the detector sampled.
 */
function refinePosition(
  x: Float64Buffer,
  y: Float64Array,
  index: number,
): number {
  if (index <= 0 || index >= x.length - 1) return x[index]!;
  const y0 = y[index - 1]!;
  const y1 = y[index]!;
  const y2 = y[index + 1]!;
  const denom = y0 - 2 * y1 + y2;
  if (denom === 0) return x[index]!;
  const delta = 0.5 * (y0 - y2) / denom;
  if (!Number.isFinite(delta) || Math.abs(delta) > 1) return x[index]!;
  const spacing = (x[index + 1]! - x[index - 1]!) / 2;
  return x[index]! + delta * spacing;
}

/** Prominence of a local maximum: its height above the higher of the two
 *  saddles separating it from any taller peak. */
function prominenceAt(y: Float64Array, index: number): number {
  const peak = y[index]!;
  let left = peak;
  for (let i = index - 1; i >= 0; i -= 1) {
    if (y[i]! > peak) break;
    if (y[i]! < left) left = y[i]!;
  }
  let right = peak;
  for (let i = index + 1; i < y.length; i += 1) {
    if (y[i]! > peak) break;
    if (y[i]! < right) right = y[i]!;
  }
  return peak - Math.max(left, right);
}

/** Find bands in a buffered spectrum, strongest first. */
export function detectPeaks(
  spectrum: BufferedSpectrum,
  options: PeakOptions = {},
): PeakProfile {
  const x = spectrum.wavenumbers;
  const y = spectrum.intensities;
  if (x.length !== y.length) {
    throw new PeakError("Wavenumber and intensity arrays must be the same length.");
  }

  const empty: PeakProfile = {
    peaks: [],
    primaryPeakCm1: null,
    peakToBackground: 0,
    baselineLevel: 0,
    noiseSigma: 0,
  };
  if (x.length < 5) return empty;

  const minSigma = options.minProminenceSigma ?? DEFAULT_MIN_PROMINENCE_SIGMA;
  const minDistance = options.minDistanceCm1 ?? DEFAULT_MIN_DISTANCE_CM1;
  const maxPeaks = options.maxPeaks ?? DEFAULT_MAX_PEAKS;

  const baseline = estimateBaseline(y, options.baselineWindow ?? DEFAULT_BASELINE_WINDOW);
  const corrected = new Float64Array(y.length);
  for (let i = 0; i < y.length; i += 1) corrected[i] = y[i]! - baseline[i]!;

  const baselineLevel = median(baseline);
  const sigma = estimateNoise(corrected);
  if (sigma <= 0) return { ...empty, baselineLevel };

  const steps: number[] = [];
  for (let i = 1; i < x.length; i += 1) steps.push(Math.abs(x[i]! - x[i - 1]!));
  const medianStep = steps.length ? median(steps) : 0;
  const distance =
    medianStep > 0 ? Math.max(1, Math.round(minDistance / medianStep)) : 1;

  const threshold = minSigma * sigma;
  const found: DetectedPeak[] = [];
  for (let i = 1; i < corrected.length - 1; i += 1) {
    const v = corrected[i]!;
    if (v <= corrected[i - 1]! || v < corrected[i + 1]!) continue;
    const prominence = prominenceAt(corrected, i);
    if (prominence < threshold) continue;
    found.push({
      cm1: refinePosition(x, corrected, i),
      height: v,
      relHeight: 0,
      prominence,
      snr: prominence / sigma,
    });
  }
  if (found.length === 0) return { ...empty, baselineLevel, noiseSigma: sigma };

  // Enforce the minimum separation, keeping the taller of any close pair.
  found.sort((a, b) => b.height - a.height || a.cm1 - b.cm1);
  const minSeparation = distance * (medianStep || 1);
  const kept: DetectedPeak[] = [];
  for (const peak of found) {
    if (kept.every((k) => Math.abs(k.cm1 - peak.cm1) >= minSeparation)) {
      kept.push(peak);
    }
    if (kept.length >= maxPeaks) break;
  }

  const strongest = kept[0]!.height;
  if (strongest <= 0) return { ...empty, baselineLevel, noiseSigma: sigma };
  for (const peak of kept) peak.relHeight = peak.height / strongest;

  // Guard the zero-baseline case rather than emitting Infinity.
  const denominator = Math.max(Math.abs(baselineLevel), sigma);
  return {
    peaks: kept,
    primaryPeakCm1: kept[0]!.cm1,
    peakToBackground: denominator > 0 ? strongest / denominator : 0,
    baselineLevel,
    noiseSigma: sigma,
  };
}

/** The bucket a position falls in, matching the server's index. */
export function binPeak(cm1: number, binWidth = PEAK_BIN_WIDTH_CM1): number {
  return Math.floor(cm1 / binWidth);
}
