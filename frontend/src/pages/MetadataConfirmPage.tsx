import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import {
  getIngestionJob,
  confirmIngestionJob,
  createSpectrum,
  type IngestionJob,
} from '../api/client';
import { Button, Card, Skeleton } from '../components/ui';

/** Review-and-confirm for extracted metadata. On a reproducibility-focused
 * platform, metadata accuracy is the product — so sanity-check flags get a
 * prominent inline callout, not just a colored input border. */
export default function MetadataConfirmPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const [job, setJob] = useState<IngestionJob | null>(null);
  const [fields, setFields] = useState<Record<string, unknown>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [spectrumId, setSpectrumId] = useState<string | null>(null);

  useEffect(() => {
    if (!jobId) return;
    getIngestionJob(jobId)
      .then((j) => {
        setJob(j);
        setFields(j.extracted_metadata_raw ?? {});
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setLoading(false));
  }, [jobId]);

  function updateField(key: string, value: string) {
    setFields((prev) => ({ ...prev, [key]: value }));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!jobId) return;
    try {
      setSubmitting(true);
      const updated = await confirmIngestionJob(jobId, fields);
      setJob(updated);
      // Confirming metadata only updates the ingestion job — it does not
      // create a Spectrum row. Do that explicitly here so "Open the
      // spectrum" below has a real id to link to.
      const spectrum = await createSpectrum({
        raw_file_id: updated.raw_file_id,
        confirmed_metadata: updated.extracted_metadata_confirmed ?? undefined,
      });
      setSpectrumId(spectrum.id);
      setConfirmed(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) {
    return (
      <div className="confirm-page">
        <h1>Confirm extracted metadata</h1>
        <Card>
          <Skeleton lines={6} height="2rem" />
        </Card>
      </div>
    );
  }
  if (error) return <p className="error">{error}</p>;
  if (!job) return <p>Ingestion job not found.</p>;

  if (confirmed && spectrumId) {
    return (
      <div className="confirm-page">
        <Card title="Metadata confirmed">
          <p>This upload is now in your private library as a draft.</p>
          <Link to={`/spectra/${spectrumId}`} className="ui-button ui-button--primary">
            Open the spectrum
          </Link>
        </Card>
      </div>
    );
  }

  const flags = job.sanity_check_flags ?? {};
  const fieldKeys = Object.keys(fields);
  const flaggedCount = fieldKeys.filter((key) => flags[key]).length;

  return (
    <div className="confirm-page">
      <h1>Confirm extracted metadata</h1>
      <p className="hint">
        Review what the parser extracted before it's committed — nothing is saved until you
        confirm.
        {flaggedCount > 0 &&
          ` ${flaggedCount} value${flaggedCount > 1 ? 's look' : ' looks'} physically implausible and ${flaggedCount > 1 ? 'are' : 'is'} highlighted below.`}
      </p>

      <Card>
        <form onSubmit={handleSubmit}>
          {fieldKeys.length === 0 && <p>No extracted metadata fields.</p>}
          <div className="confirm-grid">
            {fieldKeys.map((key) => {
              const value = fields[key];
              const flagReason = flags[key];
              const inputType = typeof value === 'number' ? 'number' : 'text';
              return (
                <div key={key} className={`field-row${flagReason ? ' flagged' : ''}`}>
                  <label htmlFor={`field-${key}`}>{key}</label>
                  <input
                    id={`field-${key}`}
                    type={inputType}
                    value={value === null || value === undefined ? '' : String(value)}
                    onChange={(e) => updateField(key, e.target.value)}
                    aria-describedby={flagReason ? `flag-${key}` : undefined}
                  />
                  {flagReason && (
                    <p id={`flag-${key}`} className="confirm-flag">
                      <span aria-hidden="true">⚠</span>
                      {flagReason}
                    </p>
                  )}
                </div>
              );
            })}
          </div>
          <div className="confirm-actions">
            <Button type="submit" variant="primary" loading={submitting}>
              Confirm metadata
            </Button>
            <span className="hint">You can still edit everything later, before publishing.</span>
          </div>
        </form>
      </Card>
    </div>
  );
}
