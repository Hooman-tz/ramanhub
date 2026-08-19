import { useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { uploadRawFile, getIngestionJob } from '../api/client';

type Phase = 'idle' | 'uploading' | 'polling' | 'done' | 'error';

const POLL_INTERVAL_MS = 1500;

export default function UploadPage() {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [phase, setPhase] = useState<Phase>('idle');
  const [message, setMessage] = useState('');
  const navigate = useNavigate();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const file = fileInputRef.current?.files?.[0];
    if (!file) {
      setMessage('Choose a file first.');
      return;
    }

    try {
      setPhase('uploading');
      setMessage('Uploading...');
      const { ingestion_job_id: jobId } = await uploadRawFile(file);

      setPhase('polling');
      setMessage('Parsing metadata...');
      await pollUntilDone(jobId);

      setPhase('done');
      setMessage('Done');
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

  return (
    <div>
      <h1>Upload raw spectral file</h1>
      <form onSubmit={handleSubmit}>
        <input ref={fileInputRef} type="file" disabled={phase === 'uploading' || phase === 'polling'} />
        <button type="submit" disabled={phase === 'uploading' || phase === 'polling'}>
          Upload
        </button>
      </form>
      {message && <p className={phase === 'error' ? 'error' : undefined}>{message}</p>}
    </div>
  );
}
