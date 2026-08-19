import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { getIngestionJob, confirmIngestionJob, type IngestionJob } from '../api/client';

export default function MetadataConfirmPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const [job, setJob] = useState<IngestionJob | null>(null);
  const [fields, setFields] = useState<Record<string, unknown>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [confirmed, setConfirmed] = useState(false);

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
      setConfirmed(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) return <p>Loading...</p>;
  if (error) return <p className="error">{error}</p>;
  if (!job) return <p>Ingestion job not found.</p>;

  if (confirmed) {
    // ASSUMPTION: the ingestion job response carries raw_file_id. If a
    // dedicated spectrum id becomes available at this step instead, swap
    // the link target below accordingly.
    return (
      <div>
        <p>Confirmed! Raw file ID: {job.raw_file_id}</p>
        <Link to={`/spectra/${job.raw_file_id}`}>View spectrum</Link>
      </div>
    );
  }

  const flags = job.sanity_check_flags ?? {};
  const fieldKeys = Object.keys(fields);

  return (
    <div>
      <h1>Confirm extracted metadata</h1>
      <p>Job status: {job.status}</p>
      <form onSubmit={handleSubmit}>
        {fieldKeys.length === 0 && <p>No extracted metadata fields.</p>}
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
              />
              {flagReason && <span className="flag-reason">{flagReason}</span>}
            </div>
          );
        })}
        <button type="submit" disabled={submitting}>
          {submitting ? 'Saving...' : 'Confirm metadata'}
        </button>
      </form>
    </div>
  );
}
