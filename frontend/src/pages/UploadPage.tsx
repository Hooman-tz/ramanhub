import { useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { uploadRawFile, getIngestionJob, startGuestSession } from '../api/client';
import { useAuth } from '../auth/useAuth';
import { Spinner } from '../components/ui';

type Phase = 'idle' | 'uploading' | 'polling' | 'error';

const POLL_INTERVAL_MS = 1500;

type QueueStatus = 'waiting' | 'uploading' | 'parsing' | 'done' | 'failed';

interface QueueItem {
  name: string;
  status: QueueStatus;
  jobId?: string;
  error?: string;
}

const STATUS_LABELS: Record<QueueStatus, string> = {
  waiting: 'Waiting',
  uploading: 'Uploading',
  parsing: 'Reading header',
  done: 'Ready to confirm',
  failed: 'Failed',
};

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
  // Tracks a guest session started by this page, so the sign-in hint can
  // switch to "you're trying it as a guest" without refetching /users/me.
  const [guestStarted, setGuestStarted] = useState(false);
  const [queue, setQueue] = useState<QueueItem[]>([]);

  function updateItem(index: number, patch: Partial<QueueItem>) {
    setQueue((current) =>
      current.map((item, i) => (i === index ? { ...item, ...patch } : item)),
    );
  }

  /** Upload several files one after another.
   *
   * Deliberately sequential, not Promise.all: each upload kicks off a
   * server-side parse, and firing a dozen at once would queue them behind
   * each other anyway while making per-file progress meaningless and the
   * failure story ("which ones landed?") much worse. One at a time is
   * slower in the best case and far clearer in every other case.
   *
   * A single file keeps the original behaviour — straight through to the
   * metadata confirm screen, since there's nothing to choose between. */
  async function ingestMany(files: File[]) {
    if (files.length === 1) {
      void ingest(files[0]);
      return;
    }

    setQueue(files.map((file) => ({ name: file.name, status: 'waiting' as QueueStatus })));
    setPhase('uploading');

    try {
      if (!authLoading && !user && !guestStarted) {
        setMessage('Starting a guest session...');
        await startGuestSession();
        setGuestStarted(true);
      }
    } catch (err) {
      setPhase('error');
      setMessage(err instanceof Error ? err.message : String(err));
      return;
    }

    for (const [index, file] of files.entries()) {
      updateItem(index, { status: 'uploading' });
      setMessage(`Uploading ${index + 1} of ${files.length}…`);
      try {
        const { ingestion_job_id: jobId } = await uploadRawFile(file);
        updateItem(index, { status: 'parsing', jobId });
        await pollUntilDone(jobId);
        updateItem(index, { status: 'done' });
      } catch (err) {
        // One bad file must not abandon the rest of the batch — record it
        // and keep going, so a single unparseable header doesn't cost the
        // user the other eleven uploads.
        updateItem(index, {
          status: 'failed',
          error: err instanceof Error ? err.message : String(err),
        });
      }
    }

    setPhase('idle');
    setMessage('');
  }

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
    const files = Array.from(e.dataTransfer.files ?? []);
    if (files.length) void ingestMany(files);
  }

  function handlePick(e: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? []);
    if (files.length) void ingestMany(files);
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
            <p className="dropzone__hint">
              or click to browse — drop several at once, up to 50 MB each
            </p>
          </>
        )}
        <input
          ref={fileInputRef}
          type="file"
          multiple
          hidden
          onChange={handlePick}
          disabled={busy}
        />
      </div>

      {queue.length > 0 && (
        <ul className="upload-queue">
          {queue.map((item, index) => (
            <li key={`${item.name}-${index}`}>
              <span className="upload-queue__name" title={item.name}>
                {item.name}
              </span>
              <span
                className={[
                  'upload-queue__status',
                  item.status === 'done' && 'upload-queue__status--done',
                  item.status === 'failed' && 'upload-queue__status--failed',
                ]
                  .filter(Boolean)
                  .join(' ')}
                title={item.error}
              >
                {STATUS_LABELS[item.status]}
              </span>
              {item.status === 'done' && item.jobId && (
                <Link
                  to={`/ingestion/${item.jobId}/confirm`}
                  className="ui-button ui-button--sm"
                >
                  Confirm
                </Link>
              )}
            </li>
          ))}
        </ul>
      )}

      {phase === 'error' && <p className="error" style={{ marginTop: 'var(--sp-3)' }}>{message}</p>}
      {(signedOut || guestStarted || user?.is_guest) && (
        <p className="hint" style={{ marginTop: 'var(--sp-3)' }}>
          {guestStarted || user?.is_guest ? (
            <>
              You're trying RamanHub as a guest. <Link to="/login">Sign in with Google</Link> to
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

      <p className="upload-vendors">
        Renishaw WiRE · Horiba LabSpec · WITec · Ocean Insight · Bruker OPUS · Thermo — anything
        else falls back to LLM-assisted header parsing.
      </p>
    </div>
  );
}
