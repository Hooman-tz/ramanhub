import { useEffect, useState } from 'react';
import { getLicenses, publishSpectrum, type License, type Spectrum } from '../api/client';

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

  useEffect(() => {
    if (spectrum.state !== 'draft') return;
    getLicenses()
      .then(setLicenses)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, [spectrum.state]);

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
