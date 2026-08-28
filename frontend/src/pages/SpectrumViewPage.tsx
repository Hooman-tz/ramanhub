import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { forkSpectrum, getSpectrum, startGuestSession, type Spectrum } from '../api/client';
import { getSpectrumData, type SpectrumData } from '../api/visualization';
import { useAuth } from '../auth/useAuth';
import LedgerStepList from '../components/LedgerStepList';
import DraftPublishToggle from '../components/DraftPublishToggle';
import PipelineBuilder from '../components/PipelineBuilder';
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

  if (loading) return <Skeleton lines={6} height="3rem" />;
  if (error) return <div className="empty-surface"><h1>We couldn’t open this spectrum</h1><p className="error">{error}</p><Link to="/library">Return to library</Link></div>;
  if (!spectrum) return <div className="empty-surface"><h1>Spectrum not found</h1><Link to="/library">Return to library</Link></div>;

  const hasPipeline = (spectrum.current_ledger?.steps?.length ?? 0) > 0;
  // Owner check gates the pipeline builder: ledgers only attach to raw
  // files you own, so non-owners get a fork card instead of a builder
  // whose Apply would 404.
  const isOwner = !authLoading && spectrum.is_owner === true;

  return (
    <div className="spectrum-page">
      <header className="spectrum-header">
        <div>
          <p className="eyebrow">{isOwner ? 'Private workspace' : 'Shared spectrum'} · {spectrum.current_ledger?.steps.length ? 'processed' : 'raw signal'}</p>
          <div className="spectrum-header__title">
            <h1>{spectrum.title ?? 'Untitled spectrum'}</h1>
            <Badge state={spectrum.state} />
          </div>
          {spectrum.description && <p className="page-intro">{spectrum.description}</p>}
        </div>
        <div className="spectrum-header__actions">
          <Link to={isOwner ? '/library' : '/search'} className="ui-button ui-button--ghost">
            {isOwner ? 'Back to library' : 'Back to search'}
          </Link>
        </div>
      </header>

      {chartError && <p className="error">{chartError}</p>}
      {chartData && (
        <Card className="chart-card">
          <div className="chart-card__heading">
            <div>
              <p className="eyebrow">Signal view</p>
              <h2>{hasPipeline ? 'Processed and raw signal shapes' : 'Raw spectrum'}</h2>
            </div>
            <span className="hint">Raman shift · cm⁻¹</span>
          </div>
          <SpectrumChart
            wavenumbers={chartData.wavenumbers}
            intensities={chartData.intensities}
            loading={chartLoading}
            name={hasPipeline ? 'Processed' : 'Raw'}
            overlay={
              hasPipeline && showRaw && rawData
                ? {
                    name: 'Raw · independent scale',
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
            {hasPipeline && showRaw && (
              <span className="chart-scale-note">
                Raw and processed traces use independent intensity axes; compare signal shape, not amplitude.
              </span>
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

      <div className="detail-grid">
        <Card title="Trust summary" className="trust-card">
          <div className="metric-row">
            <div className="metric"><span className="metric__label">Metadata</span><span className="metric__value">{spectrum.publish_readiness?.metadata_state ?? 'Not recorded'}</span></div>
            <div className="metric"><span className="metric__label">Quality control</span><span className="metric__value">{spectrum.publish_readiness?.qc_state ?? 'Not recorded'}</span></div>
            <div className="metric"><span className="metric__label">Parser confidence</span><span className="metric__value">{spectrum.provenance?.ingestion?.parser_confidence != null ? `${Math.round(spectrum.provenance.ingestion.parser_confidence * 100)}%` : 'Not recorded'}</span></div>
            <div className="metric"><span className="metric__label">DOI evidence</span><span className="metric__value">{spectrum.provenance?.publication?.verification_status === 'verified' ? 'Verified' : 'Not linked'}</span></div>
          </div>
          <div className="provenance-grid">
            <p><strong>Parser</strong><br />{spectrum.provenance?.ingestion?.parser ?? 'Not recorded'}</p>
            <p><strong>Canonical form</strong><br />{spectrum.canonicalization_version ?? spectrum.provenance?.ingestion?.canonicalization_version ?? 'Not recorded'}</p>
            <p><strong>Raw checksum</strong><br /><code>{spectrum.provenance?.raw_file?.checksum_sha256?.slice(0, 16) ?? 'Not recorded'}{spectrum.provenance?.raw_file?.checksum_sha256 ? '…' : ''}</code></p>
          </div>
        {spectrum.parent_spectrum_id && (
          <p className="hint">This private draft descends from a shared spectrum. Its source and processing record remain traceable.</p>
        )}
        {spectrum.provenance?.publication?.verification_status === 'verified' && (
          <p className="notice notice--success">DOI {spectrum.provenance.publication.doi} was verified through {spectrum.provenance.publication.provider}.</p>
        )}
        {spectrum.quality_flags && Object.keys(spectrum.quality_flags).length > 0 && (
          <details>
            <summary>Quality flags</summary>
            <ul>
              {Object.entries(spectrum.quality_flags).map(([field, reason]) => (
                <li key={field}>
                  <strong>{field}:</strong> {reason}
                </li>
              ))}
            </ul>
          </details>
        )}</Card>

        <div className="detail-grid__side">
          {isOwner ? <DraftPublishToggle spectrum={spectrum} onPublished={setSpectrum} /> : (
            <Card title="Try the processing tools">
              <p className="hint">Fork a private draft with the same source data and ledger. The original remains untouched.</p>
              <Button variant="primary" onClick={handleFork} loading={forking}>Fork to my workspace</Button>
              {forkError && <p className="error">{forkError}</p>}
            </Card>
          )}
        </div>
      </div>

      {isOwner && (
        <>
          <PipelineBuilder spectrum={spectrum} onApplied={handleApplied} />
        </>
      )}

      <Card title="Processing ledger" className="ledger-card">
        <p className="hint">A replayable record of every transformation used for the displayed signal.</p>
        <LedgerStepList steps={spectrum.current_ledger?.steps} />
      </Card>

      <VoteCommentPanel spectrumId={spectrum.id} />
    </div>
  );
}
