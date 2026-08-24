import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { forkSpectrum, getSpectrum, startGuestSession, type Spectrum } from '../api/client';
import type { Peak } from '../api/analysis';
import { getSpectrumData, type SpectrumData } from '../api/visualization';
import { useAuth } from '../auth/useAuth';
import LedgerStepList from '../components/LedgerStepList';
import DraftPublishToggle from '../components/DraftPublishToggle';
import PipelineBuilder from '../components/PipelineBuilder';
import ExportPanel from '../components/ExportPanel';
import PeakPanel from '../components/PeakPanel';
import SpectrumChart from '../components/SpectrumChart';
import VoteCommentPanel from '../components/VoteCommentPanel';
import { Badge, Button, Card, Skeleton } from '../components/ui';

export default function SpectrumViewPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { user, loading: authLoading } = useAuth();
  const [spectrum, setSpectrum] = useState<Spectrum | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [forking, setForking] = useState(false);
  const [forkError, setForkError] = useState<string | null>(null);

  const [chartData, setChartData] = useState<SpectrumData | null>(null);
  const [rawData, setRawData] = useState<SpectrumData | null>(null);
  const [chartLoading, setChartLoading] = useState(true);
  const [chartError, setChartError] = useState<string | null>(null);
  const [showRaw, setShowRaw] = useState(true);
  const [peaks, setPeaks] = useState<Peak[]>([]);
  const [showPeaks, setShowPeaks] = useState(true);

  const loadChartData = useCallback((spectrumId: string) => {
    setChartLoading(true);
    setChartError(null);
    // Raw is fetched alongside processed so the comparison is available the
    // moment a pipeline is applied — seeing what a step did to the spectrum
    // is the point of building one.
    Promise.all([getSpectrumData(spectrumId), getSpectrumData(spectrumId, { raw: true })])
      .then(([processed, raw]) => {
        setChartData(processed);
        setRawData(raw);
      })
      .catch((err) => setChartError(err instanceof Error ? err.message : String(err)))
      .finally(() => setChartLoading(false));
  }, []);

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    getSpectrum(id)
      .then(setSpectrum)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setLoading(false));
    loadChartData(id);
  }, [id, loadChartData]);

  function handleApplied(updated: Spectrum) {
    setSpectrum(updated);
    loadChartData(updated.id);
  }

  async function handleFork() {
    if (!spectrum) return;
    setForkError(null);
    setForking(true);
    try {
      // Anonymous visitors get a guest session on the spot, same
      // zero-friction rule as uploading.
      if (!user) await startGuestSession();
      const fork = await forkSpectrum(spectrum.id);
      navigate(`/spectra/${fork.id}`);
    } catch (err) {
      setForkError(err instanceof Error ? err.message : String(err));
    } finally {
      setForking(false);
    }
  }

  if (loading) return <Skeleton lines={4} height="2rem" />;
  if (error) return <p className="error">{error}</p>;
  if (!spectrum) return <p>Spectrum not found.</p>;

  const hasPipeline = (spectrum.current_ledger?.steps?.length ?? 0) > 0;
  // Owner check gates the pipeline builder: ledgers only attach to raw
  // files you own, so non-owners get a fork card instead of a builder
  // whose Apply would 404.
  const isOwner = !authLoading && user != null && user.id === spectrum.owner_id;

  return (
    <div>
      <div className="spectrum-header">
        <h1>{spectrum.title ?? `Spectrum ${spectrum.accession ?? spectrum.id}`}</h1>
        <Badge state={spectrum.state} />
        {spectrum.accession && <code className="accession">{spectrum.accession}</code>}
        {spectrum.doi && <span className="chip chip--verified">DOI-verified</span>}
      </div>
      {spectrum.description && <p className="hint">{spectrum.description}</p>}

      {chartError && <p className="error">{chartError}</p>}
      {chartData && (
        <Card className="chart-card">
          <SpectrumChart
            zoomable
            wavenumbers={chartData.wavenumbers}
            intensities={chartData.intensities}
            loading={chartLoading}
            name={hasPipeline ? 'Processed' : 'Raw'}
            peaks={showPeaks ? peaks : undefined}
            overlay={
              hasPipeline && showRaw && rawData
                ? {
                    name: 'Raw',
                    wavenumbers: rawData.wavenumbers,
                    intensities: rawData.intensities,
                  }
                : undefined
            }
          />
          <div className="chart-toolbar">
            {hasPipeline && (
              <label>
                <input
                  type="checkbox"
                  checked={showRaw}
                  onChange={(e) => setShowRaw(e.target.checked)}
                />
                Overlay the raw spectrum
              </label>
            )}
            {peaks.length > 0 && (
              <label>
                <input
                  type="checkbox"
                  checked={showPeaks}
                  onChange={(e) => setShowPeaks(e.target.checked)}
                />
                Mark detected peaks
              </label>
            )}
            {chartData.downsampled && (
              <span className="hint">
                Showing {chartData.wavenumbers.length.toLocaleString()} of{' '}
                {chartData.total_points.toLocaleString()} points (downsampled for display).
              </span>
            )}
          </div>
        </Card>
      )}
      {!chartData && chartLoading && <Skeleton height="380px" />}

      {isOwner ? (
        <>
          <PipelineBuilder spectrum={spectrum} onApplied={handleApplied} />
          <DraftPublishToggle spectrum={spectrum} onPublished={setSpectrum} />
        </>
      ) : (
        <Card title="Try the processing tools on this spectrum">
          <p className="hint">
            Fork it into your own workspace — a private draft copy with the same data and
            pipeline — and process it however you like. The original is untouched.
            {!user && ' No account needed; you can start as a guest.'}
          </p>
          <Button variant="primary" onClick={handleFork} loading={forking}>
            Fork to my workspace
          </Button>
          {forkError && <p className="error">{forkError}</p>}
        </Card>
      )}

      <PeakPanel spectrumId={spectrum.id} onPeaksChange={setPeaks} />

      <ExportPanel spectrumId={spectrum.id} hasPipeline={hasPipeline} />

      <p className="hint">
        <Link to={`/compare?ids=${spectrum.id}`}>Compare this against other spectra</Link> —
        overlay them, or run PCA and clustering across the set.
      </p>

      <h3>Applied ledger</h3>
      <LedgerStepList steps={spectrum.current_ledger?.steps} />

      <VoteCommentPanel spectrumId={spectrum.id} />
    </div>
  );
}
