// Processing-algorithm catalog (Module 2).
//
// The backend registry is the single source of truth for which steps exist
// and what params they take, so the pipeline builder renders itself from
// this response rather than hardcoding a step list that would silently rot
// every time an algorithm is added or re-versioned.

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;

/** The subset of JSON Schema the backend's param schemas actually use. */
export interface ParamProperty {
  type?: 'number' | 'integer' | 'string' | 'boolean' | 'object' | 'array';
  title?: string;
  description?: string;
  default?: unknown;
  minimum?: number;
  maximum?: number;
}

export interface ParamSchema {
  type?: string;
  properties?: Record<string, ParamProperty>;
  required?: string[];
}

export interface AlgorithmInfo {
  step_type: string;
  version: string;
  label: string;
  category: string;
  description: string;
  param_schema: ParamSchema;
  /** True for steps that change the wavenumber axis (crop, resample) — the
   * builder warns, since later steps see the shortened arrays. */
  transforms_axis: boolean;
}

export interface AlgorithmCatalog {
  categories: string[];
  algorithms: AlgorithmInfo[];
}

export const CATEGORY_LABELS: Record<string, string> = {
  despiking: 'Artifact removal',
  smoothing: 'Smoothing',
  baseline: 'Baseline / background',
  normalization: 'Normalization',
  axis: 'Wavenumber axis',
};

export async function getAlgorithmCatalog(): Promise<AlgorithmCatalog> {
  const res = await fetch(`${API_BASE_URL}/processing/algorithms`, {
    credentials: 'include',
  });
  if (!res.ok) {
    throw new Error(`API error ${res.status}: ${res.statusText}`);
  }
  return (await res.json()) as AlgorithmCatalog;
}

/** Params to send for a freshly added step: every property that declares a
 * default, so the ledger records the values actually used rather than
 * relying on the algorithm's own fallbacks. Properties without a default
 * (an optional reference wavenumber, a required crop bound) are left out
 * for the user to fill in. */
export function defaultParamsFor(algorithm: AlgorithmInfo): Record<string, unknown> {
  const params: Record<string, unknown> = {};
  for (const [key, prop] of Object.entries(algorithm.param_schema.properties ?? {})) {
    if (prop.default !== undefined) params[key] = prop.default;
  }
  return params;
}
