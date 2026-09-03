/**
 * The linear algebra the Python algorithms get from NumPy and SciPy.
 *
 * Two solvers carry everything:
 *
 * - `lstsq` (Householder QR) replaces `numpy.polyfit`/`numpy.linalg.lstsq` for
 *   the overdetermined fits — ModPoly's polynomial, MSC's slope/intercept, and
 *   Savitzky-Golay's edge handling. QR rather than the normal equations
 *   because a degree-5 Vandermonde over a few hundred points is exactly where
 *   `VᵀV` starts losing digits.
 *
 * - `whittakerSmooth` replaces `scipy.sparse.linalg.spsolve` for the two
 *   Whittaker-family baselines (ALS and airPLS). Those solve
 *   `(W + λ·DᵀD) z = W y`, and with a second-order difference operator that
 *   matrix is symmetric positive-definite and **pentadiagonal** — so a banded
 *   Cholesky runs in O(n) with a bandwidth of 2, no sparse machinery needed.
 *   This is the one port that would otherwise have pulled in a dependency.
 */

import type { Float64Buffer } from "./numeric";

/**
 * Least-squares solution of `A x ≈ b` for an overdetermined system, by
 * Householder QR with back substitution.
 */
export function lstsq(
  A: readonly (readonly number[])[],
  b: readonly number[],
): number[] {
  const m = A.length;
  const n = A[0]?.length ?? 0;
  const R = A.map((row) => [...row]);
  const y = [...b];

  for (let k = 0; k < n; k++) {
    let norm = 0;
    for (let i = k; i < m; i++) norm += R[i]![k]! ** 2;
    norm = Math.sqrt(norm);
    if (norm === 0) continue;

    // Choose the reflector sign that avoids cancellation in v[k].
    const alpha = R[k]![k]! > 0 ? -norm : norm;
    const v = new Float64Array(m);
    for (let i = k; i < m; i++) v[i] = R[i]![k]!;
    v[k] = v[k]! - alpha;

    let vtv = 0;
    for (let i = k; i < m; i++) vtv += v[i]! ** 2;
    if (vtv === 0) continue;

    for (let j = k; j < n; j++) {
      let s = 0;
      for (let i = k; i < m; i++) s += v[i]! * R[i]![j]!;
      s = (2 * s) / vtv;
      for (let i = k; i < m; i++) R[i]![j] = R[i]![j]! - s * v[i]!;
    }
    let s = 0;
    for (let i = k; i < m; i++) s += v[i]! * y[i]!;
    s = (2 * s) / vtv;
    for (let i = k; i < m; i++) y[i] = y[i]! - s * v[i]!;
  }

  const x = new Array<number>(n).fill(0);
  for (let i = n - 1; i >= 0; i--) {
    let s = y[i]!;
    for (let j = i + 1; j < n; j++) s -= R[i]![j]! * x[j]!;
    const pivot = R[i]![i]!;
    x[i] = pivot === 0 ? 0 : s / pivot;
  }
  return x;
}

/** Dense solve by Gaussian elimination with partial pivoting. Small systems only. */
function solveDense(M: number[][], rhs: number[]): number[] {
  const n = rhs.length;
  const a = M.map((row, i) => [...row, rhs[i]!]);

  for (let col = 0; col < n; col++) {
    let pivotRow = col;
    for (let r = col + 1; r < n; r++) {
      if (Math.abs(a[r]![col]!) > Math.abs(a[pivotRow]![col]!)) pivotRow = r;
    }
    if (Math.abs(a[pivotRow]![col]!) < 1e-300) {
      throw new Error("singular matrix");
    }
    [a[col], a[pivotRow]] = [a[pivotRow]!, a[col]!];
    const pivot = a[col]![col]!;
    for (let r = col + 1; r < n; r++) {
      const factor = a[r]![col]! / pivot;
      if (factor === 0) continue;
      for (let c = col; c <= n; c++) a[r]![c] = a[r]![c]! - factor * a[col]![c]!;
    }
  }

  const x = new Array<number>(n).fill(0);
  for (let i = n - 1; i >= 0; i--) {
    let s = a[i]![n]!;
    for (let j = i + 1; j < n; j++) s -= a[i]![j]! * x[j]!;
    x[i] = s / a[i]![i]!;
  }
  return x;
}

/**
 * Minimum-norm solution of an **underdetermined** `A c = y` (more unknowns
 * than equations), which is what `numpy.linalg.lstsq` returns in that case —
 * the shape `savgol_coeffs` relies on. Computed as `c = Aᵀ (A Aᵀ)⁻¹ y`; the
 * Gram matrix is only `(polyorder + 1)²`, so a dense solve is the cheap path.
 */
export function minNormSolve(
  A: readonly (readonly number[])[],
  y: readonly number[],
): number[] {
  const rows = A.length;
  const cols = A[0]?.length ?? 0;

  const gram: number[][] = [];
  for (let i = 0; i < rows; i++) {
    const row = new Array<number>(rows).fill(0);
    for (let j = 0; j < rows; j++) {
      let s = 0;
      for (let k = 0; k < cols; k++) s += A[i]![k]! * A[j]![k]!;
      row[j] = s;
    }
    gram.push(row);
  }

  const z = solveDense(gram, [...y]);
  const c = new Array<number>(cols).fill(0);
  for (let k = 0; k < cols; k++) {
    let s = 0;
    for (let i = 0; i < rows; i++) s += A[i]![k]! * z[i]!;
    c[k] = s;
  }
  return c;
}

/** `numpy.polyfit` — least-squares polynomial fit, coefficients highest power first. */
export function polyfit(
  x: ArrayLike<number>,
  y: ArrayLike<number>,
  degree: number,
): number[] {
  const m = x.length;
  const V: number[][] = [];
  for (let i = 0; i < m; i++) {
    const row = new Array<number>(degree + 1);
    let power = 1;
    // Fill right-to-left so column 0 ends up as the highest power, matching
    // NumPy's coefficient ordering.
    for (let p = degree; p >= 0; p--) {
      row[p] = power;
      power *= x[i]!;
    }
    V.push(row);
  }
  return lstsq(V, Array.from(y));
}

/**
 * Symmetric banded storage: `band[d][i]` is matrix entry `(i, i + d)`, for
 * `d = 0..p`. Only the upper triangle is stored.
 */
type SymBand = Float64Buffer[];

/**
 * Band of `DᵀD` for the `order`-th discrete difference operator `D`.
 *
 * `D` has one row per position, each holding the binomial stencil
 * (`[1, -2, 1]` for `order = 2`), so `DᵀD` is symmetric with bandwidth
 * `order`. Built by accumulating each row's outer product rather than
 * hardcoding the stencil, so raising `order` needs no new arithmetic.
 */
function differencePenaltyBand(n: number, order: number): SymBand {
  const coeffs = new Float64Array(order + 1);
  let binomial = 1;
  for (let j = 0; j <= order; j++) {
    coeffs[j] = (j % 2 === order % 2 ? 1 : -1) * binomial;
    binomial = (binomial * (order - j)) / (j + 1);
  }

  const band: SymBand = [];
  for (let d = 0; d <= order; d++) band.push(new Float64Array(n));

  for (let k = 0; k + order < n; k++) {
    for (let a = 0; a <= order; a++) {
      for (let b = a; b <= order; b++) {
        band[b - a]![k + a] = band[b - a]![k + a]! + coeffs[a]! * coeffs[b]!;
      }
    }
  }
  return band;
}

/**
 * Solve `A z = rhs` where `A` is symmetric positive-definite in band storage,
 * by banded Cholesky (`A = RᵀR`) followed by two triangular solves. O(n·p²).
 */
function bandedCholeskySolve(band: SymBand, rhs: Float64Buffer): Float64Buffer {
  const p = band.length - 1;
  const n = rhs.length;
  const R: SymBand = band.map((row) => Float64Array.from(row));

  for (let j = 0; j < n; j++) {
    let ajj = R[0]![j]!;
    for (let d = 1; d <= Math.min(p, j); d++) ajj -= R[d]![j - d]! ** 2;
    if (!(ajj > 0))
      throw new Error(
        "penalized least-squares system is not positive definite",
      );
    ajj = Math.sqrt(ajj);
    R[0]![j] = ajj;

    for (let i = 1; i <= Math.min(p, n - 1 - j); i++) {
      let s = R[i]![j]!;
      for (let d = 1; d <= Math.min(p - i, j); d++) {
        s -= R[d]![j - d]! * R[d + i]![j - d]!;
      }
      R[i]![j] = s / ajj;
    }
  }

  // Forward solve Rᵀ w = rhs.
  const w = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    let s = rhs[i]!;
    for (let k = Math.max(0, i - p); k < i; k++) s -= R[i - k]![k]! * w[k]!;
    w[i] = s / R[0]![i]!;
  }

  // Back solve R z = w.
  const z = new Float64Array(n);
  for (let i = n - 1; i >= 0; i--) {
    let s = w[i]!;
    for (let j = i + 1; j <= Math.min(n - 1, i + p); j++)
      s -= R[j - i]![i]! * z[j]!;
    z[i] = s / R[0]![i]!;
  }
  return z;
}

/**
 * Weighted penalized least-squares smoother: minimizes
 * `Σ wᵢ(yᵢ - zᵢ)² + λ Σ (Dᵒʳᵈᵉʳ z)²`.
 *
 * The exact solve `backend/app/processing/algorithms/fluorescence_suppression.py`
 * performs per airPLS iteration, and the same system `baseline_als.py` builds
 * inline. Reused by both.
 */
export function whittakerSmooth(
  y: ArrayLike<number>,
  weights: ArrayLike<number>,
  lambda: number,
  order = 2,
): Float64Buffer {
  const n = y.length;
  const band = differencePenaltyBand(n, order);
  for (let d = 0; d < band.length; d++) {
    const row = band[d]!;
    for (let i = 0; i < n; i++) row[i] = row[i]! * lambda;
  }
  for (let i = 0; i < n; i++) band[0]![i] = band[0]![i]! + weights[i]!;

  const rhs = new Float64Array(n);
  for (let i = 0; i < n; i++) rhs[i] = weights[i]! * y[i]!;

  return bandedCholeskySolve(band, rhs);
}
