/**
 * TypeScript ports of `backend/app/processing/algorithms/*.py`.
 *
 * These exist so a pipeline can be previewed at interaction speed on the
 * user's own machine. **They are not the record of truth.** The server
 * remains the only thing that materializes a `ProcessingLedger` and its
 * cached `.npz`, because a ledger records `processing_environment` — the
 * Python/platform/runtime that produced the numbers — and a browser cannot
 * honestly claim that provenance.
 *
 * Each port carries the `version` its Python sibling declared when it was
 * written. `registry.ts` compares those against the live
 * `GET /processing/algorithms` catalog and refuses to preview a step whose
 * server-side version has moved on, so drift shows up as "preview
 * unavailable" rather than as a chart that silently disagrees with what
 * Apply will produce.
 *
 * Results track the Python within floating-point reordering, not bit for
 * bit: `lstsq` here is Householder QR where NumPy uses SVD, and summation
 * orders differ. That is well inside line-width on a chart, and it is
 * precisely why previews are never persisted.
 */

import { minNormSolve, polyfit, whittakerSmooth } from "./linalg";
import type { Float64Buffer } from "./numeric";
import {
  argsort,
  interp,
  mad,
  mean,
  medfilt,
  median,
  percentile,
  polyder,
  polyval,
  std,
  trapezoid,
} from "./numeric";

/** A preview could not be computed — mirrors the Python `ValueError`s. */
export class PreviewError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PreviewError";
  }
}

type Params = Record<string, unknown>;

/* --- param coercion ------------------------------------------------------ */
/* The pipeline UI hands through whatever the JSON-Schema form produced, so
 * every read goes through a coercion that treats null/undefined/"" as absent
 * and falls back to the same default the Python declares. */

function num(params: Params, key: string, fallback: number): number {
  const v = params[key];
  if (v === undefined || v === null || v === "") return fallback;
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
}

function int(params: Params, key: string, fallback: number): number {
  return Math.trunc(num(params, key, fallback));
}

function bool(params: Params, key: string, fallback: boolean): boolean {
  const v = params[key];
  return v === undefined || v === null || v === "" ? fallback : Boolean(v);
}

/** Optional numeric param: `null` when the user left the field empty. */
function optNum(params: Params, key: string): number | null {
  const v = params[key];
  if (v === undefined || v === null || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

const copy = (v: ArrayLike<number>) => Float64Array.from(v);

/* --- despiking ----------------------------------------------------------- */

/** MAD-to-sigma scaling for a normal distribution (Iglewicz & Hoaglin). */
const MAD_SCALE = 0.6745;
/** A cosmic ray's rise and fall should be comparable; reject lopsided pairs. */
const MIN_JUMP_BALANCE = 0.2;

function modifiedZscore(values: Float64Buffer): Float64Buffer {
  const out = new Float64Array(values.length);
  const scale = mad(values);
  if (scale === 0) return out;
  const med = median(values);
  for (let i = 0; i < values.length; i++) {
    out[i] = (MAD_SCALE * (values[i]! - med)) / scale;
  }
  return out;
}

/** Robust peak-to-median height, measured on a median-filtered copy so the
 * spikes being hunted don't set the scale they're judged against. */
function dynamicRange(spectrum: Float64Buffer): number {
  const smooth = spectrum.length >= 5 ? medfilt(spectrum, 5) : spectrum;
  return percentile(smooth, 99) - median(smooth);
}

function isBalanced(rise: number, fall: number): boolean {
  const a = Math.abs(rise);
  const b = Math.abs(fall);
  return Math.min(a, b) >= MIN_JUMP_BALANCE * Math.max(a, b);
}

function despike(spectrum: Float64Buffer, params: Params): Float64Buffer {
  const threshold = num(params, "threshold", 6);
  const maxWidth = int(params, "max_width", 3);
  const minProminenceRatio = num(params, "min_prominence_ratio", 0.2);
  if (maxWidth < 1) throw new PreviewError("despike: max_width must be >= 1");

  const x = copy(spectrum);
  const n = x.length;
  if (n < 3) return x;

  // np.diff shortens by one; the leading zero realigns each score with the
  // point *after* the discontinuity, which is the spike.
  const diffs = new Float64Array(n);
  for (let i = 1; i < n; i++) diffs[i] = x[i]! - x[i - 1]!;
  const scores = modifiedZscore(diffs);

  const extreme = new Uint8Array(n);
  for (let i = 0; i < n; i++)
    extreme[i] = Math.abs(scores[i]!) > threshold ? 1 : 0;

  const bodies: { start: number; stop: number }[] = [];
  let start = 0;
  while (start < n) {
    if (!extreme[start]) {
      start++;
      continue;
    }
    let partner: number | null = null;
    const limit = Math.min(start + maxWidth + 1, n);
    for (let end = start + 1; end < limit; end++) {
      if (
        extreme[end] &&
        Math.sign(scores[end]!) !== Math.sign(scores[start]!) &&
        isBalanced(scores[start]!, scores[end]!)
      ) {
        partner = end;
        break;
      }
    }
    if (partner === null) {
      start++;
      continue;
    }
    bodies.push({ start, stop: partner });
    start = partner + 1;
  }

  const minProminence = minProminenceRatio * dynamicRange(x);
  const spikes = new Uint8Array(n);
  let flagged = 0;
  for (const body of bodies) {
    const left = body.start > 0 ? x[body.start - 1]! : x[body.stop]!;
    const right = body.stop < n ? x[body.stop]! : x[body.start - 1]!;
    const surroundings = (left + right) / 2;
    let prominence = 0;
    for (let i = body.start; i < body.stop; i++) {
      prominence = Math.max(prominence, Math.abs(x[i]! - surroundings));
    }
    if (prominence >= minProminence) {
      for (let i = body.start; i < body.stop; i++) {
        if (!spikes[i]) flagged++;
        spikes[i] = 1;
      }
    }
  }

  // Nothing to do, or nothing clean left to interpolate from.
  if (flagged === 0 || flagged === n) return x;

  const cleanIdx: number[] = [];
  const cleanVal: number[] = [];
  for (let i = 0; i < n; i++) {
    if (!spikes[i]) {
      cleanIdx.push(i);
      cleanVal.push(x[i]!);
    }
  }
  const spikeIdx: number[] = [];
  for (let i = 0; i < n; i++) if (spikes[i]) spikeIdx.push(i);

  const repaired = interp(spikeIdx, cleanIdx, cleanVal);
  for (let k = 0; k < spikeIdx.length; k++) x[spikeIdx[k]!] = repaired[k]!;
  return x;
}

/* --- smoothing ----------------------------------------------------------- */

function factorial(n: number): number {
  let acc = 1;
  for (let i = 2; i <= n; i++) acc *= i;
  return acc;
}

/**
 * `scipy.signal.savgol_coeffs(..., use="dot")` — the window weights `c` such
 * that `y[i] = Σ c[j]·x[i - half + j]`. The system is underdetermined, so the
 * minimum-norm solution is the one SciPy's `lstsq` returns.
 */
function savgolCoeffs(
  windowLength: number,
  polyorder: number,
  deriv: number,
  delta: number,
): number[] {
  const pos = windowLength >> 1;
  const xs: number[] = [];
  for (let i = 0; i < windowLength; i++) xs.push(i - pos);

  const A: number[][] = [];
  for (let p = 0; p <= polyorder; p++) A.push(xs.map((v) => v ** p));

  const rhs = new Array<number>(polyorder + 1).fill(0);
  rhs[deriv] = factorial(deriv) / delta ** deriv;
  return minNormSolve(A, rhs);
}

/**
 * The `mode="interp"` edge treatment: rather than padding, fit a polynomial
 * of the same order to the terminal window and evaluate it at the edge
 * positions.
 */
function fitEdge(
  x: Float64Buffer,
  windowStart: number,
  windowStop: number,
  interpStart: number,
  interpStop: number,
  out: Float64Buffer,
  polyorder: number,
  deriv: number,
  delta: number,
): void {
  const width = windowStop - windowStart;
  const idx = new Float64Array(width);
  const vals = new Float64Array(width);
  for (let i = 0; i < width; i++) {
    idx[i] = i;
    vals[i] = x[windowStart + i]!;
  }
  let coeffs = polyfit(idx, vals, polyorder);
  if (deriv > 0) coeffs = polyder(coeffs, deriv);
  for (let i = interpStart; i < interpStop; i++) {
    out[i] = polyval(coeffs, i - windowStart) / delta ** deriv;
  }
}

function savitzkyGolay(spectrum: Float64Buffer, params: Params): Float64Buffer {
  const windowLength = int(params, "window_length", 9);
  const polyorder = int(params, "polyorder", 3);
  const deriv = int(params, "deriv", 0);
  const delta = 1;
  const n = spectrum.length;

  if (windowLength % 2 === 0) {
    throw new PreviewError(
      `savitzky_golay: window_length must be odd, got ${windowLength}`,
    );
  }
  if (windowLength <= polyorder) {
    throw new PreviewError(
      `savitzky_golay: window_length (${windowLength}) must be greater than polyorder (${polyorder})`,
    );
  }
  if (windowLength > n) {
    throw new PreviewError(
      `savitzky_golay: window_length (${windowLength}) exceeds the spectrum length (${n})`,
    );
  }

  const half = windowLength >> 1;
  const c = savgolCoeffs(windowLength, polyorder, deriv, delta);
  const out = new Float64Array(n);
  for (let i = half; i < n - half; i++) {
    let s = 0;
    for (let j = 0; j < windowLength; j++) s += c[j]! * spectrum[i - half + j]!;
    out[i] = s;
  }
  fitEdge(spectrum, 0, windowLength, 0, half, out, polyorder, deriv, delta);
  fitEdge(
    spectrum,
    n - windowLength,
    n,
    n - half,
    n,
    out,
    polyorder,
    deriv,
    delta,
  );
  return out;
}

/* --- baselines ----------------------------------------------------------- */

function airpls(spectrum: Float64Buffer, params: Params): Float64Buffer {
  const lambda = num(params, "lambda_", 100);
  const maxIter = int(params, "max_iter", 15);
  const n = spectrum.length;

  const weights = new Float64Array(n).fill(1);
  let baseline = copy(spectrum);
  let totalAbs = 0;
  for (let i = 0; i < n; i++) totalAbs += Math.abs(spectrum[i]!);
  if (totalAbs === 0) totalAbs = 1;

  for (let iter = 1; iter <= maxIter; iter++) {
    baseline = whittakerSmooth(spectrum, weights, lambda, 2);

    let negSum = 0;
    let maxAbsResidual = 0;
    for (let i = 0; i < n; i++) {
      const residual = spectrum[i]! - baseline[i]!;
      if (residual < 0) negSum += -residual;
      maxAbsResidual = Math.max(maxAbsResidual, Math.abs(residual));
    }
    if (negSum < 1e-3 * totalAbs || iter === maxIter) break;

    // Points above the baseline are signal (weight 0); points below are
    // background, weighted by how far below they sit.
    for (let i = 0; i < n; i++) {
      const residual = spectrum[i]! - baseline[i]!;
      weights[i] = residual < 0 ? Math.exp((iter * -residual) / negSum) : 0;
    }
    const edge = Math.exp((iter * maxAbsResidual) / negSum);
    weights[0] = edge;
    weights[n - 1] = edge;
  }

  const out = new Float64Array(n);
  for (let i = 0; i < n; i++) out[i] = spectrum[i]! - baseline[i]!;
  return out;
}

function baselineAls(spectrum: Float64Buffer, params: Params): Float64Buffer {
  const lam = num(params, "lam", 1e5);
  const p = num(params, "p", 0.01);
  const maxIter = int(params, "max_iter", 10);
  const n = spectrum.length;

  const weights = new Float64Array(n).fill(1);
  let baseline = new Float64Array(n);
  for (let iter = 0; iter < maxIter; iter++) {
    baseline = whittakerSmooth(spectrum, weights, lam, 2);
    for (let i = 0; i < n; i++) {
      weights[i] = spectrum[i]! > baseline[i]! ? p : 1 - p;
    }
  }

  const out = new Float64Array(n);
  for (let i = 0; i < n; i++) out[i] = spectrum[i]! - baseline[i]!;
  return out;
}

/**
 * ModPoly (Lieber & Mahadevan-Jansen): fit, clip the working spectrum down to
 * `min(working, fit)` so peaks stop dragging the fit upward, repeat.
 */
function baselinePolynomial(
  wavenumbers: Float64Buffer,
  intensities: Float64Buffer,
  params: Params,
): [Float64Buffer, Float64Buffer] {
  const degree = int(params, "degree", 5);
  const maxIter = int(params, "max_iter", 100);
  const tol = num(params, "tol", 1e-3);
  const n = intensities.length;

  if (n <= degree) {
    throw new PreviewError(
      `baseline_polynomial: spectrum length (${n}) must exceed degree (${degree})`,
    );
  }

  // Fit against a [-1, 1] axis: a degree-5 fit over x ~ 3000 otherwise builds
  // terms around 1e17 and loses conditioning.
  let lo = Infinity;
  let hi = -Infinity;
  for (let i = 0; i < n; i++) {
    lo = Math.min(lo, wavenumbers[i]!);
    hi = Math.max(hi, wavenumbers[i]!);
  }
  const span = hi - lo;
  const x = new Float64Array(n);
  if (span > 0) {
    for (let i = 0; i < n; i++) x[i] = (2 * (wavenumbers[i]! - lo)) / span - 1;
  }

  const evaluate = (coeffs: number[]) => {
    const out = new Float64Array(n);
    for (let i = 0; i < n; i++) out[i] = polyval(coeffs, x[i]!);
    return out;
  };

  const working = copy(intensities);
  let previous = evaluate(polyfit(x, working, degree));
  for (let iter = 0; iter < maxIter; iter++) {
    for (let i = 0; i < n; i++)
      working[i] = Math.min(working[i]!, previous[i]!);
    const current = evaluate(polyfit(x, working, degree));

    let scale = 0;
    let delta = 0;
    for (let i = 0; i < n; i++) {
      scale += Math.abs(previous[i]!);
      delta += Math.abs(current[i]! - previous[i]!);
    }
    if (scale === 0) {
      previous = current;
      break;
    }
    previous = current;
    if (delta / scale < tol) break;
  }

  const out = new Float64Array(n);
  for (let i = 0; i < n; i++) out[i] = intensities[i]! - previous[i]!;
  return [wavenumbers, out];
}

/* --- normalization ------------------------------------------------------- */

function snv(spectrum: Float64Buffer, params: Params): Float64Buffer {
  const ddof = int(params, "ddof", 0);
  const sigma = std(spectrum, ddof);
  if (sigma === 0) {
    throw new PreviewError(
      "SNV is undefined for a constant (zero standard deviation) spectrum.",
    );
  }
  const mu = mean(spectrum);
  const out = new Float64Array(spectrum.length);
  for (let i = 0; i < spectrum.length; i++)
    out[i] = (spectrum[i]! - mu) / sigma;
  return out;
}

function msc(spectrum: Float64Buffer, params: Params): Float64Buffer {
  const source = params.reference_source;
  if (
    typeof source !== "object" ||
    source === null ||
    (source as { type?: unknown }).type !== "array"
  ) {
    throw new PreviewError(
      "msc requires params['reference_source'] = {'type': 'array', 'values': [...]} (inline reference spectrum).",
    );
  }
  const values = (source as { values?: unknown }).values;
  if (!Array.isArray(values)) {
    throw new PreviewError("msc: reference_source['values'] is required");
  }
  const reference = Float64Array.from(values as number[]);
  if (reference.length !== spectrum.length) {
    throw new PreviewError(
      `msc: reference length (${reference.length}) must match spectrum length (${spectrum.length})`,
    );
  }

  const [slope, intercept] = polyfit(reference, spectrum, 1) as [
    number,
    number,
  ];
  if (slope === 0) {
    throw new PreviewError(
      "msc: fitted slope is zero — reference is degenerate for this spectrum",
    );
  }
  const out = new Float64Array(spectrum.length);
  for (let i = 0; i < spectrum.length; i++)
    out[i] = (spectrum[i]! - intercept) / slope;
  return out;
}

function normalizeMinmax(spectrum: Float64Buffer, params: Params): Float64Buffer {
  const lower = num(params, "lower", 0);
  const upper = num(params, "upper", 1);
  if (upper <= lower) {
    throw new PreviewError(
      `normalize_minmax: upper (${upper}) must be greater than lower (${lower})`,
    );
  }
  let lo = Infinity;
  let hi = -Infinity;
  for (let i = 0; i < spectrum.length; i++) {
    lo = Math.min(lo, spectrum[i]!);
    hi = Math.max(hi, spectrum[i]!);
  }
  const span = hi - lo;
  if (span === 0) {
    throw new PreviewError(
      "normalize_minmax is undefined for a constant (zero-range) spectrum.",
    );
  }
  const out = new Float64Array(spectrum.length);
  for (let i = 0; i < spectrum.length; i++) {
    out[i] = lower + ((spectrum[i]! - lo) * (upper - lower)) / span;
  }
  return out;
}

function normalizeVector(spectrum: Float64Buffer): Float64Buffer {
  let sum = 0;
  for (let i = 0; i < spectrum.length; i++) sum += spectrum[i]! ** 2;
  const norm = Math.sqrt(sum);
  if (norm === 0) {
    throw new PreviewError(
      "normalize_vector is undefined for an all-zero spectrum (zero norm).",
    );
  }
  const out = new Float64Array(spectrum.length);
  for (let i = 0; i < spectrum.length; i++) out[i] = spectrum[i]! / norm;
  return out;
}

function normalizeArea(
  wavenumbers: Float64Buffer,
  intensities: Float64Buffer,
  params: Params,
): [Float64Buffer, Float64Buffer] {
  const useAbsolute = bool(params, "use_absolute", true);
  const n = wavenumbers.length;
  if (n !== intensities.length) {
    throw new PreviewError(
      "normalize_area: wavenumber and intensity arrays must match in length",
    );
  }
  if (n < 2)
    throw new PreviewError(
      "normalize_area: needs at least 2 points to integrate",
    );

  const order = argsort(wavenumbers);
  const xs = new Float64Array(n);
  const ys = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    const k = order[i]!;
    xs[i] = wavenumbers[k]!;
    ys[i] = useAbsolute ? Math.abs(intensities[k]!) : intensities[k]!;
  }
  const area = trapezoid(ys, xs);
  if (area === 0) {
    throw new PreviewError(
      "normalize_area is undefined for a spectrum with zero integrated area.",
    );
  }
  const out = new Float64Array(n);
  for (let i = 0; i < n; i++) out[i] = intensities[i]! / area;
  return [wavenumbers, out];
}

function normalizePeak(
  wavenumbers: Float64Buffer,
  intensities: Float64Buffer,
  params: Params,
): [Float64Buffer, Float64Buffer] {
  const n = wavenumbers.length;
  if (n !== intensities.length) {
    throw new PreviewError(
      "normalize_peak: wavenumber and intensity arrays must match in length",
    );
  }
  if (n === 0) throw new PreviewError("normalize_peak: empty spectrum");

  const target = optNum(params, "wavenumber");
  let reference: number;
  if (target === null) {
    reference = -Infinity;
    for (let i = 0; i < n; i++)
      reference = Math.max(reference, intensities[i]!);
  } else {
    const tolerance = Math.abs(num(params, "tolerance", 10));
    reference = -Infinity;
    let found = false;
    for (let i = 0; i < n; i++) {
      if (Math.abs(wavenumbers[i]! - target) <= tolerance) {
        found = true;
        reference = Math.max(reference, intensities[i]!);
      }
    }
    if (!found) {
      throw new PreviewError(
        `normalize_peak: no points within ±${tolerance} cm-1 of ${target} cm-1`,
      );
    }
  }

  if (reference === 0) {
    throw new PreviewError(
      "normalize_peak: the reference band has zero intensity — nothing to scale to.",
    );
  }
  const out = new Float64Array(n);
  for (let i = 0; i < n; i++) out[i] = intensities[i]! / reference;
  return [wavenumbers, out];
}

/* --- axis ---------------------------------------------------------------- */

function crop(
  wavenumbers: Float64Buffer,
  intensities: Float64Buffer,
  params: Params,
): [Float64Buffer, Float64Buffer] {
  const n = wavenumbers.length;
  if (n !== intensities.length) {
    throw new PreviewError(
      "crop: wavenumber and intensity arrays must match in length",
    );
  }
  const minCm = optNum(params, "min_cm1");
  const maxCm = optNum(params, "max_cm1");
  if (minCm === null && maxCm === null) {
    throw new PreviewError(
      "crop: at least one of min_cm1 / max_cm1 is required",
    );
  }
  if (minCm !== null && maxCm !== null && minCm >= maxCm) {
    throw new PreviewError(
      `crop: min_cm1 (${minCm}) must be less than max_cm1 (${maxCm})`,
    );
  }

  const keptX: number[] = [];
  const keptY: number[] = [];
  for (let i = 0; i < n; i++) {
    const x = wavenumbers[i]!;
    if (minCm !== null && x < minCm) continue;
    if (maxCm !== null && x > maxCm) continue;
    keptX.push(x);
    keptY.push(intensities[i]!);
  }
  if (keptX.length === 0) {
    throw new PreviewError("crop: no points fall in the requested range");
  }
  return [Float64Array.from(keptX), Float64Array.from(keptY)];
}

function resample(
  wavenumbers: Float64Buffer,
  intensities: Float64Buffer,
  params: Params,
): [Float64Buffer, Float64Buffer] {
  const n = wavenumbers.length;
  if (n !== intensities.length) {
    throw new PreviewError(
      "resample: wavenumber and intensity arrays must match in length",
    );
  }
  if (n < 2) throw new PreviewError("resample: needs at least 2 points");

  const stepCm = optNum(params, "step_cm1");
  const numPoints = optNum(params, "num_points");
  if ((stepCm === null) === (numPoints === null)) {
    throw new PreviewError(
      "resample: supply exactly one of step_cm1 or num_points",
    );
  }

  // Interpolation requires an ascending axis; vendors write either direction.
  const order = argsort(wavenumbers);
  const xs = new Float64Array(n);
  const ys = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    const k = order[i]!;
    xs[i] = wavenumbers[k]!;
    ys[i] = intensities[k]!;
  }

  let lo = optNum(params, "min_cm1") ?? xs[0]!;
  let hi = optNum(params, "max_cm1") ?? xs[n - 1]!;
  lo = Math.max(lo, xs[0]!);
  hi = Math.min(hi, xs[n - 1]!);
  if (lo >= hi) {
    throw new PreviewError(
      "resample: the requested grid does not overlap the measured range",
    );
  }

  let grid: Float64Buffer;
  if (stepCm !== null) {
    if (stepCm <= 0) {
      throw new PreviewError(
        `resample: step_cm1 must be positive, got ${stepCm}`,
      );
    }
    if (stepCm > hi - lo) {
      throw new PreviewError(
        `resample: step_cm1 (${stepCm}) is wider than the range being resampled`,
      );
    }
    const points: number[] = [];
    // Float accumulation can overshoot the endpoint; interpolating past `hi`
    // would silently extrapolate.
    for (let v = lo; v <= hi + stepCm / 2; v += stepCm) {
      if (v <= hi) points.push(v);
    }
    grid = Float64Array.from(points);
  } else {
    const count = Math.trunc(numPoints!);
    grid = new Float64Array(count);
    for (let i = 0; i < count; i++)
      grid[i] = lo + ((hi - lo) * i) / (count - 1);
  }

  return [grid, interp(grid, xs, ys)];
}

/* --- registry ------------------------------------------------------------ */

/** One ported algorithm: the version it mirrors, and how to run it. */
export interface PreviewAlgorithm {
  readonly version: string;
  readonly apply: (
    wavenumbers: Float64Buffer,
    intensities: Float64Buffer,
    params: Params,
  ) => [Float64Buffer, Float64Buffer];
}

/** Wrap an intensity-only algorithm in the axis-aware calling convention. */
function intensityOnly(
  fn: (spectrum: Float64Buffer, params: Params) => Float64Buffer,
): PreviewAlgorithm["apply"] {
  return (w, y, params) => [w, fn(y, params)];
}

export const PREVIEW_ALGORITHMS: Readonly<Record<string, PreviewAlgorithm>> = {
  "raman.despike": { version: "1.0.0", apply: intensityOnly(despike) },
  "raman.smooth.savitzky_golay": {
    version: "1.0.0",
    apply: intensityOnly(savitzkyGolay),
  },
  "raman.fluorescence_suppression.airpls": {
    version: "1.0.0",
    apply: intensityOnly(airpls),
  },
  "raman.baseline.als": { version: "1.0.0", apply: intensityOnly(baselineAls) },
  "raman.baseline.polynomial": { version: "1.0.0", apply: baselinePolynomial },
  "raman.snv": { version: "1.0.0", apply: intensityOnly(snv) },
  "raman.msc": { version: "1.0.0", apply: intensityOnly(msc) },
  "raman.normalize.minmax": {
    version: "1.0.0",
    apply: intensityOnly(normalizeMinmax),
  },
  "raman.normalize.vector": {
    version: "1.0.0",
    apply: intensityOnly((s) => normalizeVector(s)),
  },
  "raman.normalize.area": { version: "1.0.0", apply: normalizeArea },
  "raman.normalize.peak": { version: "1.0.0", apply: normalizePeak },
  "raman.crop": { version: "1.0.0", apply: crop },
  "raman.resample": { version: "1.0.0", apply: resample },
};
