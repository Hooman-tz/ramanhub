// Typed client for the discovery layer: objective-metadata search,
// spectral similarity search, and the private per-user library.
//
// Uses the shared `request<T>()` from `client.ts`. Each API module used to
// carry its own byte-identical copy of that helper; they have been
// collapsed so credentials, error unwrapping and the 204 case are defined
// once and can't drift apart.
import { request } from './client';


// ---------------------------------------------------------------------------
// Shared result shape
// ---------------------------------------------------------------------------

/** Lightweight search-result shape shared by `/search/spectra`,
 * `/search/similar/{id}`, and `/library/mine` — NOT the full spectrum
 * detail shape (`Spectrum` in `client.ts`); use `getSpectrum` for that. */
export interface SpectrumSearchResult {
  id: string;
  /** Human-quotable public identifier (RH-S-000042). */
  accession?: string | null;
  title?: string | null;
  material_type?: string | null;
  excitation_wavelength_nm?: number | null;
  snr?: number | null;
  modality: string;
  doi?: string | null;
  owner_id: string;
  published_at?: string | null;
  state: 'draft' | 'published' | 'embargoed';
}

export interface SimilarSpectrumResult {
  spectrum: SpectrumSearchResult;
  similarity: number;
}

// ---------------------------------------------------------------------------
// /search/spectra
// ---------------------------------------------------------------------------

export type TrustTier = 'doi_verified' | 'community';

export interface SearchParams {
  material_type?: string;
  excitation_wavelength_nm?: number;
  excitation_wavelength_tolerance_nm?: number;
  min_snr?: number;
  modality?: string;
  trust_tier?: TrustTier;
  limit?: number;
  offset?: number;
}

function toQueryString(params?: object): string {
  if (!params) return '';
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params as Record<string, unknown>)) {
    if (value !== undefined && value !== null && value !== '') {
      query.set(key, String(value));
    }
  }
  const qs = query.toString();
  return qs ? `?${qs}` : '';
}

/** Core objective-metadata search over the shared public commons (published
 * spectra only), ordered by `published_at desc` — never by votes/popularity. */
export async function searchSpectra(params?: SearchParams): Promise<SpectrumSearchResult[]> {
  return request<SpectrumSearchResult[]>(`/search/spectra${toQueryString(params)}`);
}

// ---------------------------------------------------------------------------
// /search/similar/{spectrum_id}
// ---------------------------------------------------------------------------

/** Cosine-similarity nearest-neighbor search against other published
 * spectra, sorted by similarity descending. */
export async function searchSimilar(
  spectrumId: string,
  topK?: number,
): Promise<SimilarSpectrumResult[]> {
  return request<SimilarSpectrumResult[]>(
    `/search/similar/${spectrumId}${toQueryString(topK !== undefined ? { top_k: topK } : undefined)}`,
  );
}

// ---------------------------------------------------------------------------
// /library/mine
// ---------------------------------------------------------------------------

export interface LibraryParams {
  material_type?: string;
  excitation_wavelength_nm?: number;
  excitation_wavelength_tolerance_nm?: number;
  min_snr?: number;
  modality?: string;
  limit?: number;
  offset?: number;
}

/** The current user's private reference library — every spectrum they own,
 * in any state (draft/published/embargoed). Requires auth. */
export async function getMyLibrary(params?: LibraryParams): Promise<SpectrumSearchResult[]> {
  return request<SpectrumSearchResult[]>(`/library/mine${toQueryString(params)}`);
}
