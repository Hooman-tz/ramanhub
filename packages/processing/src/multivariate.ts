/**
 * PCA and k-means over a set of spectra, ported from
 * `backend/app/analysis/engine.py`.
 *
 * ## Why this runs in the browser
 *
 * The analysis API deliberately does not compute for you: `execution_backend:
 * "hosted"` is refused with a 409, and a `local` run only persists a *signed
 * job envelope* describing what to compute. The design has always been that
 * the numbers are produced on the analyst's own machine.
 *
 * The lab already holds a dataset's spectra in memory, so the analyst's own
 * machine is right here. This turns exploratory PCA from something you had to
 * leave the site to do into something that happens as you click.
 *
 * These results are **exploratory and unrecorded** — nothing is written to a
 * `ProcessingLedger` or an `AnalysisRun`. A run that gets cited has to carry
 * provenance the browser cannot vouch for.
 *
 * ## Numerical approach
 *
 * The reference takes a full SVD of the standardized `n x p` matrix. With
 * `n` spectra (at most 100) and `p` grid points, `n << p`, so this instead
 * eigendecomposes the `n x n` Gram matrix `A Aᵀ = U S² Uᵀ` by cyclic Jacobi
 * and recovers `V` from it. Same subspace, same explained-variance ratios, and
 * the work is set by the spectrum count rather than the grid size.
 */

import type { Float64Buffer } from "./numeric";
import { interp } from "./numeric";

/** Matches `MIN_ANALYSIS_POINTS` in the Python engine. */
const MIN_ANALYSIS_POINTS = 16;
/** Minimum fraction of the shortest spectrum's span that must overlap. */
const MIN_OVERLAP_FRACTION = 0.8;

/** One spectrum entering the analysis, as held in the lab's buffer. */
export interface AnalysisInput {
  id: string;
  label: string;
  wavenumbers: Float64Buffer;
  intensities: Float64Buffer;
}

export interface PcaResult {
  /** Shared wavenumber grid every spectrum was interpolated onto. */
  grid: number[];
  /** `scores[i]` is spectrum `i` projected onto the retained components. */
  scores: number[][];
  /** `components[k]` is the k-th loading vector, over `grid`. */
  components: number[][];
  explainedVarianceRatio: number[];
  /** Present only when a cluster count was requested. */
  clusterLabels?: number[];
  ids: string[];
  labels: string[];
}

/** Thrown for the same conditions the server-side engine rejects. */
export class AnalysisError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "AnalysisError";
  }
}

/* --- symmetric eigendecomposition --------------------------------------- */

/**
 * Cyclic Jacobi eigendecomposition of a small symmetric matrix.
 *
 * Chosen over anything faster because `n` is capped at 100 here and Jacobi is
 * unconditionally stable for symmetric input — no pivoting, no convergence
 * tuning, and it produces a genuinely orthogonal eigenvector set, which is
 * what the score projection depends on.
 *
 * Returns eigenpairs sorted by descending eigenvalue; `vectors[i]` is the
 * eigenvector for `values[i]`.
 */
function jacobiEigen(input: readonly (readonly number[])[]): {
  values: number[];
  vectors: number[][];
} {
  const n = input.length;
  const a = input.map((row) => [...row]);
  // Eigenvectors accumulate as rows, so v[i] is the i-th eigenvector.
  const v: number[][] = Array.from({ length: n }, (_, i) =>
    Array.from({ length: n }, (_, j) => (i === j ? 1 : 0)),
  );

  for (let sweep = 0; sweep < 100; sweep++) {
    let off = 0;
    for (let p = 0; p < n; p++) {
      for (let q = p + 1; q < n; q++) off += a[p]![q]! ** 2;
    }
    if (off < 1e-30) break;

    for (let p = 0; p < n - 1; p++) {
      for (let q = p + 1; q < n; q++) {
        const apq = a[p]![q]!;
        if (Math.abs(apq) < 1e-300) continue;

        const theta = (a[q]![q]! - a[p]![p]!) / (2 * apq);
        const t =
          Math.sign(theta || 1) /
          (Math.abs(theta) + Math.sqrt(theta * theta + 1));
        const c = 1 / Math.sqrt(t * t + 1);
        const s = t * c;

        for (let k = 0; k < n; k++) {
          const akp = a[k]![p]!;
          const akq = a[k]![q]!;
          a[k]![p] = c * akp - s * akq;
          a[k]![q] = s * akp + c * akq;
        }
        for (let k = 0; k < n; k++) {
          const apk = a[p]![k]!;
          const aqk = a[q]![k]!;
          a[p]![k] = c * apk - s * aqk;
          a[q]![k] = s * apk + c * aqk;
        }
        for (let k = 0; k < n; k++) {
          const vpk = v[p]![k]!;
          const vqk = v[q]![k]!;
          v[p]![k] = c * vpk - s * vqk;
          v[q]![k] = s * vpk + c * vqk;
        }
      }
    }
  }

  const order = Array.from({ length: n }, (_, i) => i).sort(
    (i, j) => a[j]![j]! - a[i]![i]!,
  );
  return {
    values: order.map((i) => a[i]![i]!),
    vectors: order.map((i) => v[i]!),
  };
}

/* --- shared grid --------------------------------------------------------- */

/**
 * Interpolate every spectrum onto the widest grid they all cover.
 *
 * The 80% overlap floor is the server's rule, kept verbatim: comparing spectra
 * that barely share an axis produces components describing the truncation
 * rather than the chemistry.
 */
function sharedGrid(
  inputs: readonly AnalysisInput[],
  gridPoints: number,
): { grid: Float64Buffer; matrix: number[][] } {
  let left = -Infinity;
  let right = Infinity;
  let shortestSpan = Infinity;

  for (const item of inputs) {
    const x = item.wavenumbers;
    const lo = x[0]!;
    const hi = x[x.length - 1]!;
    left = Math.max(left, lo);
    right = Math.min(right, hi);
    shortestSpan = Math.min(shortestSpan, hi - lo);
  }

  if (right <= left || (right - left) / shortestSpan < MIN_OVERLAP_FRACTION) {
    throw new AnalysisError(
      "These spectra don't share enough wavenumber overlap (at least 80% is required). Crop or resample them onto a common range first.",
    );
  }

  const grid = new Float64Array(gridPoints);
  for (let i = 0; i < gridPoints; i++) {
    grid[i] = left + ((right - left) * i) / (gridPoints - 1);
  }
  const matrix = inputs.map((item) =>
    Array.from(interp(grid, item.wavenumbers, item.intensities)),
  );
  return { grid, matrix };
}

/* --- k-means ------------------------------------------------------------- */

/**
 * Lloyd's algorithm, seeded from the first `clusters` rows.
 *
 * The deterministic seed is the server's choice and worth keeping: dataset
 * membership order is stable, so the same dataset always clusters the same
 * way. A random seed would make the picture change on every click.
 */
function kmeans(
  scores: readonly (readonly number[])[],
  clusters: number,
  maxIterations = 100,
): number[] {
  const n = scores.length;
  if (clusters < 2 || clusters > n) {
    throw new AnalysisError(
      `Cluster count must be between 2 and the number of spectra (${n}).`,
    );
  }

  let centroids = scores.slice(0, clusters).map((row) => [...row]);
  let labels = new Array<number>(n).fill(0);

  for (let iter = 0; iter < maxIterations; iter++) {
    const next = scores.map((row) => {
      let best = 0;
      let bestDistance = Infinity;
      for (let c = 0; c < clusters; c++) {
        let distance = 0;
        for (let d = 0; d < row.length; d++) {
          distance += (row[d]! - centroids[c]![d]!) ** 2;
        }
        if (distance < bestDistance) {
          bestDistance = distance;
          best = c;
        }
      }
      return best;
    });

    const nextCentroids = centroids.map((centroid, c) => {
      const members = scores.filter((_, i) => next[i] === c);
      if (members.length === 0) return [...centroid];
      return centroid.map(
        (_, d) =>
          members.reduce((sum, row) => sum + row[d]!, 0) / members.length,
      );
    });

    const settled =
      next.every((label, i) => label === labels[i]) &&
      nextCentroids.every((centroid, c) =>
        centroid.every(
          (value, d) => Math.abs(value - centroids[c]![d]!) < 1e-9,
        ),
      );
    labels = next;
    centroids = nextCentroids;
    if (settled) break;
  }
  return labels;
}

/* --- PCA ----------------------------------------------------------------- */

/**
 * Standardized PCA over `inputs`, optionally followed by k-means on the scores.
 *
 * Mirrors the server engine: interpolate onto a shared grid, centre and scale
 * each column, then decompose. Columns with zero variance are scaled by 1
 * rather than dropped, matching the reference.
 */
export function analyzePca(
  inputs: readonly AnalysisInput[],
  options: {
    components?: number;
    gridPoints?: number;
    clusters?: number | null;
  } = {},
): PcaResult {
  const gridPoints = options.gridPoints ?? 128;
  const requested = options.components ?? 2;

  if (inputs.length < 2) {
    throw new AnalysisError("An analysis needs at least two spectra.");
  }
  if (gridPoints < MIN_ANALYSIS_POINTS || gridPoints > 512) {
    throw new AnalysisError(
      `Grid points must be between ${MIN_ANALYSIS_POINTS} and 512.`,
    );
  }
  if (
    inputs.some(
      (item) =>
        item.wavenumbers.length < MIN_ANALYSIS_POINTS ||
        item.intensities.length < MIN_ANALYSIS_POINTS,
    )
  ) {
    throw new AnalysisError(
      `Each spectrum needs at least ${MIN_ANALYSIS_POINTS} points.`,
    );
  }

  const { grid, matrix } = sharedGrid(inputs, gridPoints);
  const n = matrix.length;
  const p = gridPoints;

  // Centre and scale each grid column across spectra.
  const standardized: number[][] = matrix.map((row) => [...row]);
  for (let j = 0; j < p; j++) {
    let mean = 0;
    for (let i = 0; i < n; i++) mean += matrix[i]![j]!;
    mean /= n;

    let variance = 0;
    for (let i = 0; i < n; i++) variance += (matrix[i]![j]! - mean) ** 2;
    const scale = Math.sqrt(variance / n) || 1;

    for (let i = 0; i < n; i++) {
      standardized[i]![j] = (matrix[i]![j]! - mean) / scale;
    }
  }

  // Gram matrix A Aᵀ (n x n) — the small side of the decomposition.
  const gram: number[][] = Array.from({ length: n }, () =>
    new Array<number>(n).fill(0),
  );
  for (let i = 0; i < n; i++) {
    for (let k = i; k < n; k++) {
      let sum = 0;
      for (let j = 0; j < p; j++)
        sum += standardized[i]![j]! * standardized[k]![j]!;
      gram[i]![k] = sum;
      gram[k]![i] = sum;
    }
  }

  const { values, vectors } = jacobiEigen(gram);
  const componentCount = Math.min(requested, n, p);
  if (componentCount < 1) {
    throw new AnalysisError("These spectra cannot produce a PCA component.");
  }

  const totalVariance = values.reduce((sum, v) => sum + Math.max(v, 0), 0);
  const scores: number[][] = Array.from({ length: n }, () =>
    new Array<number>(componentCount).fill(0),
  );
  const components: number[][] = [];
  const explainedVarianceRatio: number[] = [];

  for (let k = 0; k < componentCount; k++) {
    const eigenvalue = Math.max(values[k]!, 0);
    const singular = Math.sqrt(eigenvalue);
    const u = vectors[k]!;

    // Loading vector v = Aᵀu / s.
    const loading = new Array<number>(p).fill(0);
    if (singular > 0) {
      for (let j = 0; j < p; j++) {
        let sum = 0;
        for (let i = 0; i < n; i++) sum += standardized[i]![j]! * u[i]!;
        loading[j] = sum / singular;
      }
    }

    // Eigenvector signs are arbitrary, so a rerun could mirror the plot for no
    // reason. Fix the sign by the largest-magnitude loading; the score sign
    // flips with it, which keeps `scores = U S` consistent.
    let extreme = 0;
    for (let j = 1; j < p; j++) {
      if (Math.abs(loading[j]!) > Math.abs(loading[extreme]!)) extreme = j;
    }
    const flip = loading[extreme]! < 0 ? -1 : 1;

    for (let j = 0; j < p; j++) loading[j] = loading[j]! * flip;
    for (let i = 0; i < n; i++) scores[i]![k] = u[i]! * singular * flip;

    components.push(loading);
    explainedVarianceRatio.push(
      totalVariance > 0 ? eigenvalue / totalVariance : 0,
    );
  }

  const result: PcaResult = {
    grid: Array.from(grid),
    scores,
    components,
    explainedVarianceRatio,
    ids: inputs.map((i) => i.id),
    labels: inputs.map((i) => i.label),
  };

  if (options.clusters != null) {
    result.clusterLabels = kmeans(scores, options.clusters);
  }
  return result;
}
