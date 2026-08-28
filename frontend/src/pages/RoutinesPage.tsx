import { useEffect, useState } from 'react';
import {
  listRoutines,
  createRoutine,
  applyRoutineToRawFile,
  updateSpectrum,
  type Routine,
  type LedgerStep,
} from '../api/client';
import { getMyLibrary, type SpectrumSearchResult } from '../api/search';
import { Button, Card, EmptyState, InputField, SelectField, TextareaField } from '../components/ui';

const KNOWN_STEP_TYPES: LedgerStep['type'][] = [
  'raman.snv',
  'raman.msc',
  'raman.fluorescence_suppression.airpls',
];

const STEP_LABELS: Record<string, string> = {
  'raman.snv': 'Standard normal variate',
  'raman.msc': 'Multiplicative scatter correction',
  'raman.fluorescence_suppression.airpls': 'Fluorescence suppression (airPLS)',
};

export default function RoutinesPage() {
  const [routines, setRoutines] = useState<Routine[]>([]);
  const [library, setLibrary] = useState<SpectrumSearchResult[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [stepType, setStepType] = useState<LedgerStep['type']>(KNOWN_STEP_TYPES[0]);
  const [paramsText, setParamsText] = useState('{}');
  const [creating, setCreating] = useState(false);

  const [selectedSpectra, setSelectedSpectra] = useState<Record<string, string>>({});
  const [applyStatus, setApplyStatus] = useState<Record<string, string>>({});

  useEffect(() => {
    refresh();
    getMyLibrary({ modality: 'raman', limit: 100 })
      .then(setLibrary)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, []);

  function refresh() {
    setLoading(true);
    listRoutines()
      .then(setRoutines)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setLoading(false));
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    let params: Record<string, unknown>;
    try {
      params = JSON.parse(paramsText);
    } catch {
      setError('Params must be valid JSON.');
      return;
    }

    try {
      setCreating(true);
      setError(null);
      await createRoutine({
        // Raman is the only modality RamanHub supports today (see the
        // architecture doc's namespacing note) — hardcoded rather than
        // exposed as a choice until mass spec/NMR land.
        modality: 'raman',
        name,
        description,
        steps_template: [{ type: stepType, version: '1', params }],
      });
      setName('');
      setDescription('');
      setParamsText('{}');
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setCreating(false);
    }
  }

  async function handleApply(routineId: string) {
    const spectrumId = selectedSpectra[routineId];
    const spectrum = library.find((candidate) => candidate.id === spectrumId);
    if (!spectrum?.raw_file_id) {
      setApplyStatus((prev) => ({ ...prev, [routineId]: 'Choose a spectrum from your library first.' }));
      return;
    }
    try {
      setApplyStatus((prev) => ({ ...prev, [routineId]: 'Applying...' }));
      const applied = await applyRoutineToRawFile(spectrum.raw_file_id, routineId);
      await updateSpectrum(spectrum.id, { current_ledger_id: applied.ledger_id });
      setApplyStatus((prev) => ({
        ...prev,
        [routineId]: `Applied to ${spectrum.title ?? spectrum.id}.`,
      }));
    } catch (err) {
      setApplyStatus((prev) => ({
        ...prev,
        [routineId]: err instanceof Error ? err.message : String(err),
      }));
    }
  }

  return (
    <div className="workspace-page">
      <header className="page-header">
        <div>
          <p className="eyebrow">Reusable processing</p>
          <h1>Routines</h1>
          <p className="page-intro">Save a repeatable preparation step and apply it to a spectrum in your private library.</p>
        </div>
      </header>

      <Card title="Create a routine" className="routine-create">
        <form onSubmit={handleCreate}>
          <div className="routine-create__grid">
            <InputField label="Routine name" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Fluorescence clean-up" required />
            <InputField label="Purpose (optional)" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="When to use this routine" />
            <SelectField label="Processing method" value={stepType} onChange={(e) => setStepType(e.target.value as LedgerStep['type'])}>
              {KNOWN_STEP_TYPES.map((t) => (
                <option key={t} value={t}>{STEP_LABELS[t] ?? t}</option>
              ))}
            </SelectField>
            <TextareaField
              label="Advanced parameters (JSON)"
              hint="Leave {} to use the algorithm’s validated defaults."
              rows={3}
              value={paramsText}
              onChange={(e) => setParamsText(e.target.value)}
            />
          </div>
          <div className="inline-actions">
            <Button type="submit" variant="primary" loading={creating}>Save routine</Button>
            <span className="hint">Routines do not modify source files.</span>
          </div>
        </form>
      </Card>

      {error && <p className="error">{error}</p>}
      {loading && <p>Loading routines...</p>}

      {!loading && routines.length === 0 && <EmptyState title="No saved routines yet"><p>Create one above to apply a consistent preparation step across your library.</p></EmptyState>}

      {routines.map((routine) => (
        <Card key={routine.id} title={routine.name} className="routine-card">
          {routine.description && <p className="hint">{routine.description}</p>}
          <p className="routine-card__steps">
            {routine.steps_template.map((step) => STEP_LABELS[step.type] ?? step.type.replace(/^raman\./, '')).join(' → ')}
          </p>
          <div className="routine-card__apply">
            <SelectField
              label="Apply to a saved spectrum"
              value={selectedSpectra[routine.id] ?? ''}
              onChange={(e) => setSelectedSpectra((prev) => ({ ...prev, [routine.id]: e.target.value }))}
            >
              <option value="">Choose from your Raman library...</option>
              {library.map((spectrum) => (
                <option key={spectrum.id} value={spectrum.id}>
                  {spectrum.title ?? 'Untitled spectrum'} · {spectrum.state}
                </option>
              ))}
            </SelectField>
            <Button type="button" onClick={() => handleApply(routine.id)}>Apply routine</Button>
          </div>
          {applyStatus[routine.id] && <p className="hint" role="status">{applyStatus[routine.id]}</p>}
        </Card>
      ))}
    </div>
  );
}
