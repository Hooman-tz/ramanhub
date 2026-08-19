import { useEffect, useState } from 'react';
import { getLicenses, publishSpectrum, updateSpectrum, type License, type Spectrum } from '../api/client';
import { lookupDoi, type DoiMetadata } from '../api/visualization';

interface Props {
  spectrum: Spectrum;
  onPublished: (updated: Spectrum) => void;
}

export default function DraftPublishToggle({ spectrum, onPublished }: Props) {
  const [licenses, setLicenses] = useState<License[]>([]);
  const [licenseId, setLicenseId] = useState('');
  const [embargoDate, setEmbargoDate] = useState('');
  const [publishing, setPublishing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // --- DOI lookup (auto-populate paper metadata instead of manual entry) ---
  // Looked-up metadata is shown as a read-only preview for the user to
  // review (never auto-submitted). "Use this metadata" persists
  // title/description onto the draft via PATCH /spectra/{id}. The raw DOI
  // string itself (once looked up, regardless of whether its metadata was
  // "applied") is sent along with the publish request below — that's what
  // marks the spectrum DOI-verified for Module 4's trust-tier search filter.
  const [doiInput, setDoiInput] = useState('');
  const [doiLookupLoading, setDoiLookupLoading] = useState(false);
  const [doiMetadata, setDoiMetadata] = useState<DoiMetadata | null>(null);
  const [doiNotFound, setDoiNotFound] = useState(false);
  const [doiError, setDoiError] = useState<string | null>(null);
  const [applyingDoiMetadata, setApplyingDoiMetadata] = useState(false);

  useEffect(() => {
    if (spectrum.state !== 'draft') return;
    getLicenses()
      .then(setLicenses)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, [spectrum.state]);

  async function handleDoiLookup() {
    if (!doiInput.trim()) {
      setDoiError('Enter a DOI first.');
      return;
    }
    setDoiError(null);
    setDoiNotFound(false);
    setDoiMetadata(null);
    try {
      setDoiLookupLoading(true);
      const result = await lookupDoi(doiInput.trim());
      if (result === null) {
        setDoiNotFound(true);
      } else {
        setDoiMetadata(result);
      }
    } catch (err) {
      setDoiError(err instanceof Error ? err.message : String(err));
    } finally {
      setDoiLookupLoading(false);
    }
  }

  async function handleApplyDoiMetadata() {
    if (!doiMetadata) return;
    try {
      setApplyingDoiMetadata(true);
      setDoiError(null);
      const authorsSuffix = doiMetadata.authors.length ? ` (${doiMetadata.authors.join(', ')})` : '';
      const journalSuffix = doiMetadata.journal
        ? ` — ${doiMetadata.journal}${doiMetadata.year ? ` (${doiMetadata.year})` : ''}`
        : '';
      const updated = await updateSpectrum(spectrum.id, {
        title: doiMetadata.title ?? spectrum.title,
        description: `${authorsSuffix.trim()}${journalSuffix}`.trim() || spectrum.description,
      });
      onPublished(updated);
    } catch (err) {
      setDoiError(err instanceof Error ? err.message : String(err));
    } finally {
      setApplyingDoiMetadata(false);
    }
  }

  async function handlePublish() {
    if (!licenseId) {
      setError('Choose a license first.');
      return;
    }
    try {
      setPublishing(true);
      setError(null);
      const updated = await publishSpectrum(spectrum.id, {
        license_id: licenseId,
        embargo_release_at: embargoDate ? new Date(embargoDate).toISOString() : null,
        // Only send a DOI that actually resolved via lookup (doiMetadata is
        // set) — an unverified/typo'd DOI string shouldn't be able to mark
        // a spectrum "DOI-verified" for the trust-tier search filter.
        doi: doiMetadata ? doiInput.trim() : null,
      });
      onPublished(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPublishing(false);
    }
  }

  return (
    <div>
      <span className={`badge ${spectrum.state}`}>{spectrum.state}</span>

      {spectrum.state === 'draft' && (
        <div style={{ marginTop: '0.75rem' }}>
          <div className="field-row">
            <label htmlFor="doi-input">Paper DOI (optional)</label>
            <input
              id="doi-input"
              type="text"
              placeholder="10.1021/acs.analchem.xxxxxxx"
              value={doiInput}
              onChange={(e) => {
                setDoiInput(e.target.value);
                setDoiMetadata(null);
                setDoiNotFound(false);
              }}
            />
            <button type="button" onClick={handleDoiLookup} disabled={doiLookupLoading}>
              {doiLookupLoading ? 'Looking up...' : 'Look up'}
            </button>
          </div>

          {doiError && <p className="error">{doiError}</p>}
          {doiNotFound && <p>No metadata found for that DOI.</p>}

          {doiMetadata && (
            <div className="doi-preview" style={{ margin: '0.5rem 0', padding: '0.5rem', border: '1px solid #ccc' }}>
              <p>
                <strong>{doiMetadata.title ?? '(no title found)'}</strong>
              </p>
              {doiMetadata.authors.length > 0 && <p>{doiMetadata.authors.join(', ')}</p>}
              {(doiMetadata.journal || doiMetadata.year) && (
                <p>
                  {doiMetadata.journal ?? ''} {doiMetadata.year ? `(${doiMetadata.year})` : ''}
                </p>
              )}
              {doiMetadata.url && (
                <p>
                  <a href={doiMetadata.url} target="_blank" rel="noreferrer">
                    {doiMetadata.url}
                  </a>
                </p>
              )}
              <p>
                This is a preview only — review it, then apply it to this draft's title/description
                if it's correct.
              </p>
              <button type="button" onClick={handleApplyDoiMetadata} disabled={applyingDoiMetadata}>
                {applyingDoiMetadata ? 'Applying...' : 'Use this metadata'}
              </button>
            </div>
          )}

          <div className="field-row">
            <label htmlFor="license-select">License</label>
            <select
              id="license-select"
              value={licenseId}
              onChange={(e) => setLicenseId(e.target.value)}
            >
              <option value="">Select a license...</option>
              {licenses.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.name}
                </option>
              ))}
            </select>
          </div>

          <div className="field-row">
            <label htmlFor="embargo-date">Embargo release date (optional)</label>
            <input
              id="embargo-date"
              type="date"
              value={embargoDate}
              onChange={(e) => setEmbargoDate(e.target.value)}
            />
          </div>

          <button type="button" onClick={handlePublish} disabled={publishing}>
            {publishing ? 'Publishing...' : 'Publish'}
          </button>

          {error && <p className="error">{error}</p>}
        </div>
      )}
    </div>
  );
}
