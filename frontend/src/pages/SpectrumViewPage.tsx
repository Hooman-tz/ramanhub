import { useCallback, useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { getSpectrum, type Spectrum } from '../api/client';
import { getSpectrumData, type SpectrumData } from '../api/visualization';
import LedgerStepList from '../components/LedgerStepList';
import DraftPublishToggle from '../components/DraftPublishToggle';
import PipelineBuilder from '../components/PipelineBuilder';
import SpectrumChart from '../components/SpectrumChart';
import VoteCommentPanel from '../components/VoteCommentPanel';
import { Badge, Card, Skeleton } from '../components/ui';

export default function SpectrumViewPage() {
  const { id } = useParams<{ id: string }>();
  const [spectrum, setSpectrum] = useState<Spectrum | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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

  if (loading) return <Skeleton lines={4} height="2rem" />;
  if (error) return <p className="error">{error}</p>;
  if (!spectrum) return <p>Spectrum not found.</p>;

  const hasPipeline = (spectrum.current_ledger?.steps?.length ?? 0) > 0;

  return (
    <div>
      <div className="spectrum-header">
        <h1>{spectrum.title ?? `Spectrum ${spectrum.id}`}</h1>
        <Badge state={spectrum.state} />
      </div>
      {spectrum.description && <p className="hint">{spectrum.description}</p>}

      {chartError && <p className="error">{chartError}</p>}
      {chartData && (
        <Card className="chart-card">
          <SpectrumChart
            wavenumbers={chartData.wavenumbers}
            intensities={chartData.intensities}
            loading={chartLoading}
            name={hasPipeline ? 'Processed' : 'Raw'}
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

      <PipelineBuilder spectrum={spectrum} onApplied={handleApplied} />

      <DraftPublishToggle spectrum={spectrum} onPublished={setSpectrum} />

      <h3>Applied ledger</h3>
      <LedgerStepList steps={spectrum.current_ledger?.steps} />

      <VoteCommentPanel spectrumId={spectrum.id} />
    </div>
  );
}
