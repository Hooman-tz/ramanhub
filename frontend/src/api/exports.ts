// Download and citation.
//
// Downloads are plain links, not fetches: letting the browser handle the
// navigation means it applies the server's Content-Disposition filename and
// streams straight to disk, instead of us buffering a whole spectrum into a
// Blob in memory to hand back to the same browser.

import { API_BASE_URL, request } from './client';

export type DownloadFormat = 'csv' | 'tsv' | 'json' | 'jcamp';
export type CitationFormat = 'bibtex' | 'ris' | 'text';
export type Stage = 'processed' | 'raw';

export const DOWNLOAD_FORMATS: Array<{ value: DownloadFormat; label: string; hint: string }> = [
  { value: 'csv', label: 'CSV', hint: 'Opens anywhere — Excel, Origin, pandas' },
  { value: 'tsv', label: 'TSV', hint: 'Tab-separated, same as CSV' },
  {
    value: 'jcamp',
    label: 'JCAMP-DX',
    hint: 'The spectroscopy interchange format — opens directly in WiRE, LabSpec, OMNIC',
  },
  { value: 'json', label: 'JSON', hint: 'Arrays plus metadata, for scripting' },
];

export function spectrumDownloadUrl(
  spectrumId: string,
  format: DownloadFormat = 'csv',
  stage: Stage = 'processed',
): string {
  return `${API_BASE_URL}/spectra/${spectrumId}/download?format=${format}&stage=${stage}`;
}

/** Fetch a citation as text, for a copy-to-clipboard block.
 *
 * Uses `fetch` rather than a link because the citation is shown inline; the
 * endpoint only sets Content-Disposition when `download=true`. */
export async function getCitation(
  spectrumId: string,
  format: CitationFormat = 'bibtex',
): Promise<string> {
  const res = await fetch(
    `${API_BASE_URL}/spectra/${spectrumId}/citation?format=${format}`,
    { credentials: 'include' },
  );
  if (!res.ok) {
    throw new Error(`Couldn't build a citation (${res.status}).`);
  }
  return res.text();
}

export function citationDownloadUrl(spectrumId: string, format: CitationFormat): string {
  return `${API_BASE_URL}/spectra/${spectrumId}/citation?format=${format}&download=true`;
}

/** Re-exported so callers that need a generic request don't import from two
 * modules. */
export { request };
