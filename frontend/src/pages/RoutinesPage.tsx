import { useEffect, useState } from 'react';
import {
  listRoutines,
  createRoutine,
  applyRoutineToRawFile,
  type Routine,
  type LedgerStep,
} from '../api/client';

const KNOWN_STEP_TYPES: LedgerStep['type'][] = [
  'raman.snv',
  'raman.msc',
  'raman.fluorescence_suppression.airpls',
];

export default function RoutinesPage() {
  const [routines, setRoutines] = useState<Routine[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [stepType, setStepType] = useState<LedgerStep['type']>(KNOWN_STEP_TYPES[0]);
  const [paramsText, setParamsText] = useState('{}');
  const [creating, setCreating] = useState(false);

  const [applyInputs, setApplyInputs] = useState<Record<string, string>>({});
  const [applyStatus, setApplyStatus] = useState<Record<string, string>>({});

  useEffect(() => {
    refresh();
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
        name,
        description,
        steps: [{ type: stepType, version: '1', params }],
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
    const rawFileId = applyInputs[routineId];
    if (!rawFileId) {
      setApplyStatus((prev) => ({ ...prev, [routineId]: 'Enter a raw file ID first.' }));
      return;
    }
    try {
      setApplyStatus((prev) => ({ ...prev, [routineId]: 'Applying...' }));
      await applyRoutineToRawFile(rawFileId, routineId);
      setApplyStatus((prev) => ({ ...prev, [routineId]: 'Applied.' }));
    } catch (err) {
      setApplyStatus((prev) => ({
        ...prev,
        [routineId]: err instanceof Error ? err.message : String(err),
      }));
    }
  }

  return (
    <div>
      <h1>Routines</h1>

      <fieldset>
        <legend>Create routine</legend>
        <form onSubmit={handleCreate}>
          <div className="field-row">
            <label htmlFor="routine-name">Name</label>
            <input id="routine-name" value={name} onChange={(e) => setName(e.target.value)} required />
          </div>
          <div className="field-row">
            <label htmlFor="routine-description">Description</label>
            <input
              id="routine-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
          <div className="field-row">
            <label htmlFor="routine-step-type">Step type</label>
            <select
              id="routine-step-type"
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
            <label htmlFor="routine-params">Params (JSON)</label>
            <textarea
              id="routine-params"
              rows={3}
              value={paramsText}
              onChange={(e) => setParamsText(e.target.value)}
            />
          </div>
          <button type="submit" disabled={creating}>
            {creating ? 'Creating...' : 'Create routine'}
          </button>
        </form>
      </fieldset>

      {error && <p className="error">{error}</p>}
      {loading && <p>Loading routines...</p>}

      {!loading && routines.length === 0 && <p>No routines yet.</p>}

      {routines.map((routine) => (
        <fieldset key={routine.id}>
          <legend>{routine.name}</legend>
          {routine.description && <p>{routine.description}</p>}
          <pre>{JSON.stringify(routine.steps, null, 2)}</pre>

          <div className="field-row">
            <label htmlFor={`apply-${routine.id}`}>Raw file ID</label>
            <input
              id={`apply-${routine.id}`}
              value={applyInputs[routine.id] ?? ''}
              onChange={(e) =>
                setApplyInputs((prev) => ({ ...prev, [routine.id]: e.target.value }))
              }
            />
          </div>
          <button type="button" onClick={() => handleApply(routine.id)}>
            Apply to raw file
          </button>
          {applyStatus[routine.id] && <p>{applyStatus[routine.id]}</p>}
        </fieldset>
      ))}
    </div>
  );
}
