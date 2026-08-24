// Visualization + DOI-lookup API calls.
//
// Uses the shared `request<T>()` from `client.ts` — see the note there.
import { request } from './client';


// ---------------------------------------------------------------------------
// Spectrum chart data
// ---------------------------------------------------------------------------

export interface SpectrumData {
  wavenumbers: number[];
  intensities: number[];
  downsampled: boolean;
  total_points: number;
}

/** Chart-ready spectrum arrays. Pass `raw: true` to get the unprocessed
 * spectrum regardless of which ledger is attached — that's what the
 * pipeline builder overlays behind the processed result. */
export async function getSpectrumData(
  spectrumId: string,
  options: { maxPoints?: number; raw?: boolean } = {},
): Promise<SpectrumData> {
  const query = new URLSearchParams({ max_points: String(options.maxPoints ?? 2000) });
  if (options.raw) query.set('raw', 'true');
  return request<SpectrumData>(`/spectra/${spectrumId}/data?${query}`);
}

// ---------------------------------------------------------------------------
// DOI lookup (Crossref-backed metadata auto-population)
// ---------------------------------------------------------------------------

export interface DoiMetadata {
  doi: string;
  title?: string;
  authors: string[];
  journal?: string;
  year?: number;
  url?: string;
}

/** Looks up `doi` via the backend's `/doi-lookup` endpoint. Returns `null`
 * (rather than throwing) when the DOI isn't found (HTTP 404) — callers
 * should treat that as "no metadata available", not an error state. Any
 * other failure (network error, 5xx, etc.) still throws. */
export async function lookupDoi(doi: string): Promise<DoiMetadata | null> {
  try {
    return await request<DoiMetadata>(`/doi-lookup?doi=${encodeURIComponent(doi)}`);
  } catch (err) {
    if (err instanceof Error && err.message.startsWith('API error 404')) {
      return null;
    }
    throw err;
  }
}
