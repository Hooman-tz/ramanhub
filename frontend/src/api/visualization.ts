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
// Pipeline preview
// ---------------------------------------------------------------------------

export interface PreviewStep {
  type: string;
  params: Record<string, unknown>;
  order: number;
}

/** "What WOULD this pipeline do" — replays `steps` against the raw spectrum
 * and returns the resulting curve without committing anything.
 *
 * A POST rather than a GET because the pipeline goes in the body: a
 * multi-step pipeline with nested params doesn't survive a query string, and
 * putting it there would also write every parameter the user tried into
 * access logs.
 *
 * The server persists nothing for a preview — see `app/processing/preview.py`
 * for why that needs its own compute path rather than the caching one. */
export async function previewPipeline(
  spectrumId: string,
  steps: PreviewStep[],
  options: { maxPoints?: number } = {},
): Promise<SpectrumData> {
  return request<SpectrumData>(`/spectra/${spectrumId}/preview`, {
    method: 'POST',
    body: JSON.stringify({ steps, max_points: options.maxPoints ?? 2000 }),
  });
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
