import { useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { uploadRawFile, getIngestionJob } from '../api/client';
import { useAuth } from '../auth/useAuth';
import { Spinner } from '../components/ui';

type Phase = 'idle' | 'uploading' | 'polling' | 'error';

const POLL_INTERVAL_MS = 1500;

/** The front door. "/" lands here: one glass drop zone, nothing else to
 * read first — the architecture doc's "straight into the toolbox, closer to
 * opening a chat app than reading an academic poster," taken literally. */
export default function UploadPage() {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [phase, setPhase] = useState<Phase>('idle');
  const [message, setMessage] = useState('');
  const [dragOver, setDragOver] = useState(false);
  const navigate = useNavigate();
  const { user, loading: authLoading } = useAuth();

  const busy = phase === 'uploading' || phase === 'polling';

  async function ingest(file: File) {
    try {
      setPhase('uploading');
      setMessage(`Uploading ${file.name}...`);
      const { ingestion_job_id: jobId } = await uploadRawFile(file);

      setPhase('polling');
      setMessage('Reading the header and extracting metadata...');
      await pollUntilDone(jobId);

      navigate(`/ingestion/${jobId}/confirm`);
    } catch (err) {
      setPhase('error');
      setMessage(err instanceof Error ? err.message : String(err));
    }
  }

  async function pollUntilDone(jobId: string): Promise<void> {
    // eslint-disable-next-line no-constant-condition
    while (true) {
      const job = await getIngestionJob(jobId);
      if (job.status === 'succeeded') return;
      if (job.status === 'failed') {
        throw new Error(job.error_message ?? 'Ingestion job failed.');
      }
      await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
    }
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(false);
    if (busy) return;
    const file = e.dataTransfer.files?.[0];
    if (file) void ingest(file);
  }

  function handlePick(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) void ingest(file);
    // Reset so re-picking the same file re-triggers change.
    e.target.value = '';
  }

  const signedOut = !authLoading && !user;

  return (
    <div className="upload-hero">
      <h1 className="upload-hero__title">Drop a spectrum in</h1>
      <p className="upload-hero__tagline">
        Raw files stay immutable — every processing step is recorded and replayable.
      </p>

      <div
        className={[
          'glass-panel',
          'dropzone',
          dragOver && 'dropzone--active',
          busy && 'dropzone--busy',
        ]
          .filter(Boolean)
          .join(' ')}
        role="button"
        tabIndex={0}
        aria-label="Upload a raw spectral file"
        onClick={() => !busy && fileInputRef.current?.click()}
        onKeyDown={(e) => {
          if ((e.key === 'Enter' || e.key === ' ') && !busy) {
            e.preventDefault();
            fileInputRef.current?.click();
          }
        }}
        onDragOver={(e) => {
          e.preventDefault();
          if (!busy) setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
      >
        {busy ? (
          <>
            <Spinner />
            <p className="dropzone__title">{message}</p>
            <p className="dropzone__hint">
              Metadata will be shown for your review before anything is committed.
            </p>
          </>
        ) : (
          <>
            <svg
              className="dropzone__icon"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M12 15V4m0 0 4.5 4.5M12 4 7.5 8.5" />
              <path d="M3.5 15.5v2a3 3 0 0 0 3 3h11a3 3 0 0 0 3-3v-2" />
            </svg>
            <p className="dropzone__title">
              {dragOver ? 'Release to upload' : 'Drag a raw file here'}
            </p>
            <p className="dropzone__hint">or click to browse — up to 50 MB</p>
          </>
        )}
        <input ref={fileInputRef} type="file" hidden onChange={handlePick} disabled={busy} />
      </div>

      {phase === 'error' && <p className="error" style={{ marginTop: 'var(--sp-3)' }}>{message}</p>}
      {signedOut && (
        <p className="hint" style={{ marginTop: 'var(--sp-3)' }}>
          You'll need to <Link to="/login">sign in</Link> before uploading.
        </p>
      )}

      <p className="upload-vendors">
        Renishaw WiRE · Horiba LabSpec · WITec · Ocean Insight · Bruker OPUS · Thermo — anything
        else falls back to LLM-assisted header parsing.
      </p>
    </div>
  );
}
