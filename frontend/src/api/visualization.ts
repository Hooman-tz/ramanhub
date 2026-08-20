// Visualization + DOI-lookup API calls (Module 3).
//
// ASSUMPTIONS: same posture as api/client.ts — these endpoint shapes are
// "best effort" against the Module 3 backend spec, not yet confirmed
// against a live backend.

// `client.ts`'s `request<T>()` helper is not exported (module-private), so
// this file has its own small fetch wrapper matching the same
// credentials/base-URL/error-handling pattern.
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    credentials: 'include',
    ...init,
    headers: {
      ...(init?.body && !(init.body instanceof FormData) ? { 'Content-Type': 'application/json' } : {}),
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
