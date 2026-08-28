import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import {
  getIngestionJob,
  confirmIngestionJob,
  retryIngestionJob,
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

  function metadataForConfirmation(): Record<string, unknown> {
    const numericFields = new Set([
      'laser_wavelength_nm',
      'laser_power_mw',
      'integration_time_ms',
      'accumulations',
      'resolution_cm1',
      'grating_lines_mm',
      'objective_magnification',
    ]);
    return Object.fromEntries(
      Object.entries(fields).map(([key, value]) => {
        if (value === '') return [key, null];
        if (numericFields.has(key) && typeof value === 'string') return [key, Number(value)];
        return [key, value];
      }),
    );
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!jobId) return;
    try {
      setSubmitting(true);
      const updated = await confirmIngestionJob(jobId, metadataForConfirmation());
      setJob(updated);
      if (!updated.draft_spectrum_id) {
        throw new Error('The draft could not be recovered from this confirmed ingestion.');
      }
      setSpectrumId(updated.draft_spectrum_id);
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
        <p className="eyebrow">Step 2 of 3 · Review</p>
        <h1>Confirm the sample metadata</h1>
        <Card>
          <Skeleton lines={6} height="2rem" />
        </Card>
      </div>
    );
  }
  if (error) return <p className="error">{error}</p>;
  if (!job) return <p>Ingestion job not found.</p>;

  if (job.status === 'failed') {
    return (
      <div className="confirm-page">
        <p className="eyebrow">Ingestion stopped</p>
        <Card title="This file needs another analysis attempt">
          <p className="error">{job.error_message ?? 'The parser could not read this file.'}</p>
          <p className="hint">
            The original file remains private and unchanged. You can retry the same durable job
            without uploading a duplicate.
          </p>
          <Button
            onClick={() => {
              setSubmitting(true);
              retryIngestionJob(job.id)
                .then(setJob)
                .catch((err) => setError(err instanceof Error ? err.message : String(err)))
                .finally(() => setSubmitting(false));
            }}
            loading={submitting}
          >
            Retry analysis
          </Button>
        </Card>
      </div>
    );
  }

  if (job.status !== 'succeeded') {
    return (
      <div className="confirm-page">
        <p className="eyebrow">Step 1 of 3 · Ingest</p>
        <Card title="Analysis in progress">
          <p className="hint">
            This durable job is still being processed. Refresh this page in a moment; your upload
            remains private while it is analyzed.
          </p>
          <Button onClick={() => getIngestionJob(job.id).then(setJob)} loading={submitting}>
            Refresh status
          </Button>
        </Card>
      </div>
    );
  }

  if (confirmed && spectrumId) {
    return (
      <div className="confirm-page">
        <p className="eyebrow">Ready for processing</p>
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
  const fieldKeys = Object.keys(fields).filter((key) => key !== 'raw_extra_fields');
  const flaggedCount = fieldKeys.filter((key) => flags[key]).length;

  return (
    <div className="confirm-page">
      <p className="eyebrow">Step 2 of 3 · Review</p>
      <div className="page-header">
        <div>
          <h1>Confirm the sample metadata</h1>
          <p className="page-intro">Check the parser’s interpretation before this draft enters your private library.</p>
        </div>
      </div>
      <Card className="ingestion-status" title="Extraction evidence">
        <div className="status-item">
          <span className="status-label">Parser</span>
          <strong>
          {job.parser_used?.startsWith('llm:')
            ? 'AI-assisted extraction'
            : `Parser: ${job.parser_used ?? 'unknown'}`}
          </strong>
        </div>
        <div className="status-item">
          <span className="status-label">Confidence</span>
          <strong>
          {job.parser_confidence === undefined || job.parser_confidence === null
            ? 'not available'
            : `${Math.round(job.parser_confidence * 100)}%`}
          </strong>
        </div>
        <div className="status-item">
          <span className="status-label">Canonical form</span>
          <strong>{job.canonicalization_version ?? 'pending'}</strong>
        </div>
      </Card>
      <p className="hint">
        Review what the parser extracted before it becomes the confirmed metadata on your private
        draft. The original upload and parser output are retained privately for provenance.
        {flaggedCount > 0 &&
          ` ${flaggedCount} value${flaggedCount > 1 ? 's look' : ' looks'} physically implausible and ${flaggedCount > 1 ? 'are' : 'is'} highlighted below.`}
      </p>

      <Card className="metadata-editor">
        {flaggedCount > 0 && (
          <div className="notice notice--warning" role="status">
            <strong>Review {flaggedCount} flagged value{flaggedCount === 1 ? '' : 's'}</strong>
            <span>These values look physically implausible and need your confirmation.</span>
          </div>
        )}
        <form onSubmit={handleSubmit}>
          {fieldKeys.length === 0 && <p>No extracted metadata fields.</p>}
          {Boolean(fields.raw_extra_fields) && (
            <p className="hint">
              Additional parser fields are retained with the raw record and are not edited here.
            </p>
          )}
          <div className="confirm-grid">
            {fieldKeys.map((key) => {
              const value = fields[key];
              const flagReason = flags[key];
              const inputType = typeof value === 'number' ? 'number' : 'text';
              return (
                <div key={key} className={`field-row${flagReason ? ' flagged' : ''}`}>
                    <label htmlFor={`field-${key}`}>{key.split('_').join(' ')}</label>
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
