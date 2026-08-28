// Typed client for Module 4a's discovery layer: core objective-metadata
// search, spectral similarity search, and the private per-user library.
// `client.ts` doesn't export its `request<T>()` helper, so this is a small
// local fetch wrapper following the exact same pattern (same base URL env
// var, same `credentials: 'include'` cookie-auth convention, same
// error-shape unwrapping) rather than editing `client.ts` — mirrors
// `api/social.ts`'s identical approach for the same reason.
//
// ASSUMPTIONS: the backend for this module is authored by this same pass,
// but is still "best effort" relative to what the eventual integration
// point (SpectrumViewPage, App.tsx routes) expects — reconcile field names
// if needed.

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    credentials: 'include',
    ...init,
    headers: {
      ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
      ...init?.headers,
    },
  });

  if (!res.ok) {
    let detail: string | undefined;
    try {
      const body = await res.json();
      detail = body?.detail ?? body?.message ?? JSON.stringify(body);
    } catch {
      detail = await res.text().catch(() => undefined);
    }
    throw new Error(`API error ${res.status}: ${detail ?? res.statusText}`);
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// ---------------------------------------------------------------------------
// Shared result shape
// ---------------------------------------------------------------------------

/** Lightweight search-result shape shared by `/search/spectra`,
 * `/search/similar/{id}`, and `/library/mine` — NOT the full spectrum
 * detail shape (`Spectrum` in `client.ts`); use `getSpectrum` for that. */
export interface SpectrumSearchResult {
  id: string;
  title?: string | null;
  material_type?: string | null;
  excitation_wavelength_nm?: number | null;
  snr?: number | null;
  modality: string;
  doi?: string | null;
  published_at?: string | null;
  state: 'draft' | 'published' | 'embargoed';
  raw_file_id?: string;
  metadata_state?: 'confirmed' | 'needs_review';
  qc_state?: 'passed' | 'review' | 'blocked';
  publish_ready?: boolean;
}

export interface SimilarSpectrumResult {
  spectrum: SpectrumSearchResult;
  similarity: number;
  overlap_fraction: number;
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
