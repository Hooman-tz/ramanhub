/**
 * The NumPy/SciPy primitives the ported algorithms lean on.
 *
 * Each function here mirrors one specific NumPy or SciPy call used by
 * `backend/app/processing/algorithms/`, including the edge-case behaviour
 * that matters for the result (zero-padding in `medfilt`, linear
 * interpolation in `percentile`, endpoint clamping in `interp`). Anywhere the
 * reference implementation's convention is non-obvious, it is named in a
 * comment — those conventions are the difference between a preview that
 * tracks the server and one that quietly diverges.
 */

/**
 * Every array in this package is a `Float64Array` over a plain `ArrayBuffer`.
 * Naming it explicitly keeps the ported algorithms from drifting between the
 * `ArrayBuffer` and `ArrayBufferLike` instantiations that TypeScript's generic
 * typed arrays otherwise infer at each construction site.
 */
export type Float64Buffer = Float64Array<ArrayBuffer>;

/** Ascending sort of a copy. Used wherever NumPy would sort in place. */
function sorted(values: ArrayLike<number>): Float64Buffer {
  const out = Float64Array.from(values);
  out.sort();
  return out;
}

export function mean(values: ArrayLike<number>): number {
  let total = 0;
  for (let i = 0; i < values.length; i++) total += values[i]!;
  return total / values.length;
}

/** `numpy.std(ddof=...)`. `ddof = 0` is the population standard deviation. */
export function std(values: ArrayLike<number>, ddof = 0): number {
  const mu = mean(values);
  let sum = 0;
  for (let i = 0; i < values.length; i++) sum += (values[i]! - mu) ** 2;
  return Math.sqrt(sum / (values.length - ddof));
}

export function median(values: ArrayLike<number>): number {
  const s = sorted(values);
  const n = s.length;
  if (n === 0) return NaN;
  const mid = n >> 1;
  return n % 2 === 1 ? s[mid]! : (s[mid - 1]! + s[mid]!) / 2;
}

/** Median absolute deviation about the median — the MAD in `despike`. */
export function mad(values: ArrayLike<number>): number {
  const med = median(values);
  const deviations = new Float64Array(values.length);
  for (let i = 0; i < values.length; i++)
    deviations[i] = Math.abs(values[i]! - med);
  return median(deviations);
}

/**
 * `numpy.percentile` with the default `linear` interpolation: the value at
 * fractional rank `q/100 * (n - 1)`, interpolated between its neighbours.
 */
export function percentile(values: ArrayLike<number>, q: number): number {
  const s = sorted(values);
  const n = s.length;
  if (n === 0) return NaN;
  if (n === 1) return s[0]!;
  const rank = (q / 100) * (n - 1);
  const lo = Math.floor(rank);
  const hi = Math.ceil(rank);
  if (lo === hi) return s[lo]!;
  return s[lo]! + (rank - lo) * (s[hi]! - s[lo]!);
}

/**
 * `scipy.signal.medfilt` — a sliding median with an odd kernel, **zero
 * padded** at both ends. The zero padding is not incidental: it is what
 * `despike._dynamic_range` measures against, so matching it matters.
 */
export function medfilt(
  values: ArrayLike<number>,
  kernel: number,
): Float64Buffer {
  const n = values.length;
  const out = new Float64Array(n);
  const half = kernel >> 1;
  const window = new Float64Array(kernel);
  for (let i = 0; i < n; i++) {
    for (let k = 0; k < kernel; k++) {
      const idx = i + k - half;
      window[k] = idx < 0 || idx >= n ? 0 : values[idx]!;
    }
    out[i] = median(window);
  }
  return out;
}

/**
 * `numpy.interp` — piecewise-linear interpolation that **clamps** rather than
 * extrapolates outside `[xp[0], xp[n-1]]`. `xp` must be ascending.
 *
 * Walks `xq` and `xp` together instead of binary-searching per query, because
 * every caller here passes an ascending `xq`.
 */
export function interp(
  xq: ArrayLike<number>,
  xp: ArrayLike<number>,
  fp: ArrayLike<number>,
): Float64Buffer {
  const out = new Float64Array(xq.length);
  const last = xp.length - 1;
  let j = 0;
  for (let i = 0; i < xq.length; i++) {
    const x = xq[i]!;
    if (x <= xp[0]!) {
      out[i] = fp[0]!;
      continue;
    }
    if (x >= xp[last]!) {
      out[i] = fp[last]!;
      continue;
    }
    while (j < last - 1 && xp[j + 1]! < x) j++;
    const x0 = xp[j]!;
    const x1 = xp[j + 1]!;
    const span = x1 - x0;
    out[i] =
      span === 0 ? fp[j]! : fp[j]! + ((x - x0) / span) * (fp[j + 1]! - fp[j]!);
  }
  return out;
}

/** Indices that would sort `values` ascending — `numpy.argsort`. */
export function argsort(values: ArrayLike<number>): Int32Array {
  const idx = new Int32Array(values.length);
  for (let i = 0; i < values.length; i++) idx[i] = i;
  return idx.sort((a, b) => values[a]! - values[b]!);
}

/** `numpy.trapezoid(y, x)` — trapezoidal integration over a non-uniform axis. */
export function trapezoid(y: ArrayLike<number>, x: ArrayLike<number>): number {
  let total = 0;
  for (let i = 1; i < y.length; i++) {
    total += ((x[i]! - x[i - 1]!) * (y[i]! + y[i - 1]!)) / 2;
  }
  return total;
}

/** `numpy.polyval` — coefficients highest power first. */
export function polyval(coeffs: ArrayLike<number>, x: number): number {
  let acc = 0;
  for (let i = 0; i < coeffs.length; i += 1) {
    acc = acc * x + coeffs[i]!;
  }
  return acc;
}

/** `numpy.polyder` — the `m`-th derivative, coefficients highest power first. */
export function polyder(coeffs: readonly number[], m: number): number[] {
  let current = [...coeffs];
  for (let round = 0; round < m; round++) {
    const degree = current.length - 1;
    if (degree <= 0) return [0];
    const next: number[] = [];
    for (let i = 0; i < degree; i++) next.push(current[i]! * (degree - i));
    current = next;
  }
  return current;
}
