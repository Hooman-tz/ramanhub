/**
 * `@ramanhub/processing` — a client-side mirror of the server's processing
 * toolbox, for **previewing** a pipeline at interaction speed.
 *
 * ## Why this exists
 *
 * `POST /raw-files/{id}/ledgers` computes synchronously on the request path:
 * it downloads the raw file from object storage, replays every step in
 * NumPy/SciPy, compresses the result, uploads a `.npz` back, and commits a
 * cache row — all before responding. That is the right amount of work for a
 * pipeline someone is committing to. It is far too much for a slider drag,
 * and the cache cannot help there: the cache key covers the exact step
 * params, so every parameter change is a guaranteed miss.
 *
 * ## The split
 *
 * - **Preview (here).** Runs on the user's machine against a buffered copy of
 *   the raw spectrum. No network, no ledger row, no stored artifact. Free to
 *   recompute on every keystroke, free to throw away.
 * - **Commit (server).** Still the only path that creates a `ProcessingLedger`
 *   and its cached output. The ledger records `processing_environment` — the
 *   Python and platform that produced the numbers — so a published result is
 *   always something the server actually computed.
 *
 * ## Drift protection
 *
 * Each port pins the algorithm version it was written against. Pass the live
 * catalog from `GET /processing/algorithms` to `previewPipeline` and any step
 * whose server-side version has moved on returns `unsupported` instead of a
 * chart that quietly disagrees with what Apply will produce.
 */

import type { Float64Buffer } from "./numeric";
import { PREVIEW_ALGORITHMS, PreviewError } from "./algorithms";

export { PreviewError } from "./algorithms";
export { analyzePca, AnalysisError } from "./multivariate";
export type { AnalysisInput, PcaResult } from "./multivariate";

/** A spectrum held in the client-side working buffer. */
export interface BufferedSpectrum {
  wavenumbers: Float64Buffer;
  intensities: Float64Buffer;
}

/** One pipeline step, in the same shape the ledger API accepts. */
export interface PreviewStep {
  type: string;
  params: Record<string, unknown>;
}

export type PreviewOutcome =
  | { status: "ok"; spectrum: BufferedSpectrum; elapsedMs: number }
  /** No local port for a step, or the server's version has moved past ours. */
  | { status: "unsupported"; reason: string }
  /** A step ran and rejected its input — the same complaint the server makes. */
  | { status: "error"; reason: string; failedStepType: string };

/** Step types this package can run locally. */
export const PREVIEW_STEP_TYPES: readonly string[] =
  Object.keys(PREVIEW_ALGORITHMS);

/** The algorithm version each local port mirrors, keyed by step type. */
export const PREVIEW_ALGORITHM_VERSIONS: Readonly<Record<string, string>> =
  Object.fromEntries(
    Object.entries(PREVIEW_ALGORITHMS).map(([type, algo]) => [
      type,
      algo.version,
    ]),
  );

/** Convenience for turning a JSON array from the API into a working buffer. */
export function toBuffer(
  wavenumbers: readonly number[],
  intensities: readonly number[],
): BufferedSpectrum {
  return {
    wavenumbers: Float64Array.from(wavenumbers),
    intensities: Float64Array.from(intensities),
  };
}

/**
 * Why a pipeline can't be previewed locally, or `null` if it can.
 *
 * `catalogVersions` maps `step_type` to the version the server currently
 * ships (from `GET /processing/algorithms`). Omit it to skip the parity check
 * — useful before the catalog has loaded, at the cost of the drift guarantee.
 */
export function previewBlocker(
  steps: readonly PreviewStep[],
  catalogVersions?: Readonly<Record<string, string>>,
): string | null {
  for (const step of steps) {
    const algo = PREVIEW_ALGORITHMS[step.type];
    if (!algo) return `${step.type} has no local implementation`;
    const serverVersion = catalogVersions?.[step.type];
    if (serverVersion !== undefined && serverVersion !== algo.version) {
      return `${step.type} is v${serverVersion} on the server but v${algo.version} locally`;
    }
  }
  return null;
}

/**
 * Replay `steps` over `source` locally.
 *
 * Never mutates `source` — the buffer is the cached raw spectrum and gets
 * reused for every recompute, so each step works on its own arrays.
 */
export function previewPipeline(
  source: BufferedSpectrum,
  steps: readonly PreviewStep[],
  catalogVersions?: Readonly<Record<string, string>>,
): PreviewOutcome {
  const blocker = previewBlocker(steps, catalogVersions);
  if (blocker) return { status: "unsupported", reason: blocker };

  const startedAt = performance.now();
  let wavenumbers = Float64Array.from(source.wavenumbers);
  let intensities = Float64Array.from(source.intensities);

  for (const step of steps) {
    // `previewBlocker` already proved every step resolves.
    const algo = PREVIEW_ALGORITHMS[step.type]!;
    try {
      [wavenumbers, intensities] = algo.apply(
        wavenumbers,
        intensities,
        step.params,
      );
    } catch (e) {
      const reason =
        e instanceof PreviewError || e instanceof Error
          ? e.message
          : "This step could not be applied.";
      return { status: "error", reason, failedStepType: step.type };
    }
  }

  return {
    status: "ok",
    spectrum: { wavenumbers, intensities },
    elapsedMs: performance.now() - startedAt,
  };
}
