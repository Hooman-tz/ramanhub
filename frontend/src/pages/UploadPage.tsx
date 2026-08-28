import { useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  uploadRawFile,
  getIngestionJob,
  retryIngestionJob,
  startGuestSession,
} from '../api/client';
import { useAuth } from '../auth/useAuth';
import { Button, Card, Spinner } from '../components/ui';

type Phase = 'idle' | 'uploading' | 'polling' | 'timeout' | 'error';

const POLL_INTERVAL_MS = 1500;

class IngestionTimeoutError extends Error {}

/** The front door. "/" lands here: one glass drop zone, nothing else to
 * read first — the architecture doc's "straight into the toolbox, closer to
 * opening a chat app than reading an academic poster," taken literally. */
export default function UploadPage() {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [phase, setPhase] = useState<Phase>('idle');
  const [message, setMessage] = useState('');
  const [dragOver, setDragOver] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const navigate = useNavigate();
  const { user, loading: authLoading } = useAuth();

  const busy = phase === 'uploading' || phase === 'polling';
  // Tracks a guest session started by this page, so the sign-in hint can
  // switch to "you're trying it as a guest" without refetching /users/me.
  const [guestStarted, setGuestStarted] = useState(false);

  async function ingest(file: File) {
    try {
      // No account? Start a guest session on the spot — trying the tools
      // should be zero-friction; identity is only needed to publish.
      if (!authLoading && !user && !guestStarted) {
        setPhase('uploading');
        setMessage('Starting a guest session...');
        await startGuestSession();
        setGuestStarted(true);
      }
      setPhase('uploading');
      setMessage(`Uploading ${file.name}...`);
      const uploaded = await uploadRawFile(file);
      const jobId = uploaded.ingestion_job_id;
      setJobId(jobId);
      sessionStorage.setItem('spectra-insight:last-ingestion-job', jobId);

      setPhase('polling');
      setMessage(
        uploaded.deduplicated
          ? 'Resuming the existing analysis for this file...'
          : 'Reading the header and extracting metadata...',
      );
      await pollUntilDone(jobId);

      navigate(`/ingestion/${jobId}/confirm`);
    } catch (err) {
      setPhase(err instanceof IngestionTimeoutError ? 'timeout' : 'error');
      setMessage(err instanceof Error ? err.message : String(err));
    }
  }

  async function pollUntilDone(jobId: string): Promise<void> {
    for (let attempt = 0; attempt < 80; attempt += 1) {
      const job = await getIngestionJob(jobId);
      if (job.status === 'succeeded') return;
      if (job.status === 'failed') {
        throw new Error(job.error_message ?? 'Ingestion job failed.');
      }
      await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
    }
    throw new IngestionTimeoutError(
      'Analysis is taking longer than expected. Your upload is safe; retry its status from this page.',
    );
  }

  async function retryAnalysis() {
    if (!jobId) return;
    try {
      setPhase('polling');
      setMessage('Retrying analysis...');
      await retryIngestionJob(jobId);
      await pollUntilDone(jobId);
      navigate(`/ingestion/${jobId}/confirm`);
    } catch (err) {
      setPhase(err instanceof IngestionTimeoutError ? 'timeout' : 'error');
      setMessage(err instanceof Error ? err.message : String(err));
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
    <div className="upload-hero workspace-page">
      <div className="upload-hero__intro">
        <p className="eyebrow">New analysis</p>
        <h1 className="upload-hero__title">Start with the raw signal</h1>
        <p className="upload-hero__tagline">
          Upload a spectrum to extract metadata, review quality, and build a reproducible path to publication.
        </p>
      </div>

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
              Raw data stays private while we read the file. You’ll review metadata before it is committed.
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
            <p className="dropzone__hint">or click to browse · up to 50 MB</p>
          </>
        )}
        <input ref={fileInputRef} type="file" hidden onChange={handlePick} disabled={busy} />
      </div>

      {(phase === 'error' || phase === 'timeout') && (
        <Card className={`upload-recovery upload-recovery--${phase}`} title={phase === 'timeout' ? 'Still processing' : 'We couldn’t read this file'}>
          <p className={phase === 'timeout' ? 'hint' : 'error'}>{message}</p>
          <p className="hint">
            {phase === 'timeout'
              ? 'The upload is safe. Check its status or retry analysis without uploading a duplicate.'
              : 'Your original file remains unchanged. You can try the analysis again.'}
          </p>
          {jobId && (
            <Button type="button" variant={phase === 'timeout' ? 'glass' : 'primary'} onClick={() => void retryAnalysis()}>
              {phase === 'timeout' ? 'Retry analysis' : 'Try again'}
            </Button>
          )}
        </Card>
      )}
      {(signedOut || guestStarted || user?.is_guest) && (
        <p className="hint" style={{ marginTop: 'var(--sp-3)' }}>
          {guestStarted || user?.is_guest ? (
            <>
               You’re trying Spectra Insight as a guest. <Link to="/login">Sign in with Google</Link> to
              publish, vote, and keep this work in your account.
            </>
          ) : (
            <>
              No account needed — drop a file to try it as a guest.{' '}
              <Link to="/login">Sign in</Link> to publish and keep a private library.
            </>
          )}
        </p>
      )}

      <div className="upload-steps" aria-label="Analysis steps">
        <div><span>01</span><strong>Ingest</strong><small>Read the raw file</small></div>
        <div><span>02</span><strong>Review</strong><small>Confirm extracted metadata</small></div>
        <div><span>03</span><strong>Process</strong><small>Record every transformation</small></div>
      </div>
      <p className="upload-vendors">Works with Renishaw WiRE, Horiba LabSpec, WITec, Ocean Insight, Bruker OPUS, Thermo, and more.</p>
    </div>
  );
}
