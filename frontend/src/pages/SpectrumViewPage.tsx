import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import {
  getSpectrum,
  createLedger,
  updateSpectrum,
  type Spectrum,
  type LedgerStep,
} from '../api/client';
import { getSpectrumData, type SpectrumData } from '../api/visualization';
import LedgerStepList from '../components/LedgerStepList';
import DraftPublishToggle from '../components/DraftPublishToggle';
import SpectrumChart from '../components/SpectrumChart';
import VoteCommentPanel from '../components/VoteCommentPanel';

const KNOWN_STEP_TYPES: LedgerStep['type'][] = [
  'raman.snv',
  'raman.msc',
  'raman.fluorescence_suppression.airpls',
];

export default function SpectrumViewPage() {
  const { id } = useParams<{ id: string }>();
  const [spectrum, setSpectrum] = useState<Spectrum | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [stepType, setStepType] = useState<LedgerStep['type']>(KNOWN_STEP_TYPES[0]);
  const [paramsText, setParamsText] = useState('{}');
  const [addingStep, setAddingStep] = useState(false);
  const [stepError, setStepError] = useState<string | null>(null);

  const [chartData, setChartData] = useState<SpectrumData | null>(null);
  const [chartLoading, setChartLoading] = useState(true);
  const [chartError, setChartError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    loadSpectrum(id);
  }, [id]);

  function loadSpectrum(spectrumId: string) {
    setLoading(true);
    getSpectrum(spectrumId)
      .then(setSpectrum)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setLoading(false));
    loadChartData(spectrumId);
  }

  function loadChartData(spectrumId: string) {
    setChartLoading(true);
    setChartError(null);
    getSpectrumData(spectrumId)
      .then(setChartData)
      .catch((err) => setChartError(err instanceof Error ? err.message : String(err)))
      .finally(() => setChartLoading(false));
  }

  async function handleAddStep(e: React.FormEvent) {
    e.preventDefault();
    if (!spectrum) return;
    setStepError(null);

    let params: Record<string, unknown>;
    try {
      params = JSON.parse(paramsText);
    } catch {
      setStepError('Params must be valid JSON.');
      return;
    }

    const existingSteps = spectrum.current_ledger?.steps ?? [];
    // Backend resolves each step's algorithm version server-side — only
    // type/params/order are sent (see createLedger() in api/client.ts).
    const newSteps = [...existingSteps, { type: stepType, params }].map((s, order) => ({
      type: s.type,
      params: s.params,
      order,
    }));

    const rawFileId = spectrum.raw_file_id;
    if (!rawFileId) {
      setStepError('Spectrum has no raw_file_id to attach a new ledger to.');
      return;
    }

    try {
      setAddingStep(true);
      const { ledger_id } = await createLedger(rawFileId, newSteps);
      // Creating a ledger doesn't attach it to the spectrum — that's a
      // separate, explicit step, consistent with drafts staying editable
      // until the owner chooses what "current" means for them.
      await updateSpectrum(spectrum.id, { current_ledger_id: ledger_id });
      loadSpectrum(spectrum.id);
    } catch (err) {
      setStepError(err instanceof Error ? err.message : String(err));
    } finally {
      setAddingStep(false);
    }
  }

  if (loading) return <p>Loading...</p>;
  if (error) return <p className="error">{error}</p>;
  if (!spectrum) return <p>Spectrum not found.</p>;

  return (
    <div>
      <h1>{spectrum.title ?? `Spectrum ${spectrum.id}`}</h1>
      {spectrum.description && <p>{spectrum.description}</p>}

      <DraftPublishToggle spectrum={spectrum} onPublished={setSpectrum} />

      <h2>Processing ledger</h2>
      <LedgerStepList steps={spectrum.current_ledger?.steps} />

      <h3>Add step</h3>
      <form onSubmit={handleAddStep}>
        <div className="field-row">
          <label htmlFor="step-type">Step type</label>
          <select
            id="step-type"
            value={stepType}
            onChange={(e) => setStepType(e.target.value as LedgerStep['type'])}
          >
            {KNOWN_STEP_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </div>
        <div className="field-row">
          <label htmlFor="step-params">Params (JSON)</label>
          <textarea
            id="step-params"
            rows={4}
            value={paramsText}
            onChange={(e) => setParamsText(e.target.value)}
          />
        </div>
        <button type="submit" disabled={addingStep}>
          {addingStep ? 'Adding...' : 'Add step'}
        </button>
        {stepError && <p className="error">{stepError}</p>}
      </form>

      <h2>Data</h2>
      {chartError && <p className="error">{chartError}</p>}
      {chartData && (
        <>
          <SpectrumChart
            wavenumbers={chartData.wavenumbers}
            intensities={chartData.intensities}
            loading={chartLoading}
          />
          {chartData.downsampled && (
            <p className="hint">
              Showing {chartData.wavenumbers.length.toLocaleString()} of{' '}
              {chartData.total_points.toLocaleString()} points (downsampled for display).
            </p>
          )}
        </>
      )}
      {!chartData && chartLoading && <p>Loading chart...</p>}

      <VoteCommentPanel spectrumId={spectrum.id} />
    </div>
  );
}
