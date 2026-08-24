// Analysis endpoints: peak detection, PCA, HCA.
//
// These describe a spectrum rather than transforming it, which is why they
// live outside the processing/ledger API — see `app/analysis/__init__.py` on
// the backend for the full reasoning.

import { request } from './client';

export interface Peak {
  index: number;
  wavenumber: number;
  intensity: number;
  prominence: number;
  fwhm_cm1: number | null;
  area: number;
}

export interface PeakResult {
  spectrum_id: string;
  peaks: Peak[];
  params: Record<string, unknown>;
  version: string;
  /** Which arrays the peaks were found on — "processed" or "raw". Recorded
   * so a quoted peak list can't be misread as applying to the other one. */
  stage: string;
}

export interface PeakOptions {
  prominence_fraction?: number;
  min_distance_cm1?: number;
  noise_multiple?: number;
  max_peaks?: number;
  raw?: boolean;
}

export async function detectPeaks(
  spectrumId: string,
  options: PeakOptions = {},
): Promise<PeakResult> {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(options)) {
    if (value !== undefined && value !== null) params.set(key, String(value));
  }
  const query = params.toString();
  return request<PeakResult>(`/spectra/${spectrumId}/peaks${query ? `?${query}` : ''}`);
}

export interface PcaResult {
  spectrum_ids: string[];
  wavenumbers: number[];
  /** (N spectra x K components) — where each spectrum sits in PC space. */
  scores: number[][];
  /** (K components x P wavenumbers) — what each PC *is*, spectrally. This
   * is what makes a PCA plot interpretable rather than decorative. */
  loadings: number[][];
  explained_variance_ratio: number[];
  n_components: number;
  n_spectra: number;
  version: string;
}

export async function runPca(payload: {
  spectrum_ids: string[];
  n_components?: number;
  mean_center?: boolean;
  scale?: boolean;
  raw?: boolean;
}): Promise<PcaResult> {
  return request<PcaResult>('/analysis/pca', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export interface HcaResult {
  spectrum_ids: string[];
  /** scipy linkage matrix: [left, right, distance, count] per merge. */
  linkage_matrix: number[][];
  leaf_order: number[];
  labels: number[] | null;
  distances: number[];
  n_spectra: number;
  version: string;
}

export async function runHca(payload: {
  spectrum_ids: string[];
  metric?: string;
  method?: string;
  n_clusters?: number | null;
  raw?: boolean;
}): Promise<HcaResult> {
  return request<HcaResult>('/analysis/hca', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export interface AnalysisCatalogEntry {
  version: string;
  param_schema: { type: string; properties: Record<string, Record<string, unknown>> };
  defaults: Record<string, unknown>;
}

export interface AnalysisCatalog {
  peaks: AnalysisCatalogEntry;
  pca: AnalysisCatalogEntry;
  hca: AnalysisCatalogEntry;
}

/** Parameter schemas + defaults, so analysis controls render from the
 * server's declaration rather than hardcoded UI — the same pattern the
 * pipeline builder uses for `/processing/algorithms`. */
export async function getAnalysisCatalog(): Promise<AnalysisCatalog> {
  return request<AnalysisCatalog>('/analysis/catalog');
}
