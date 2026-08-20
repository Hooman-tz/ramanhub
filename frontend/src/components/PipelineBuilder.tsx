import { useEffect, useMemo, useState } from 'react';
import { createLedger, updateSpectrum, type Spectrum } from '../api/client';
import {
  CATEGORY_LABELS,
  defaultParamsFor,
  getAlgorithmCatalog,
  type AlgorithmCatalog,
  type AlgorithmInfo,
} from '../api/processing';
import ParamField from './ParamField';
import { Button, Card, SelectField, Skeleton } from './ui';

interface DraftStep {
  type: string;
  params: Record<string, unknown>;
}

interface Props {
  spectrum: Spectrum;
  onApplied: (spectrum: Spectrum) => void;
}

/** Compact one-line rendering of a step's params for its collapsed state. */
function paramsSummary(params: Record<string, unknown>): string {
  const entries = Object.entries(params);
  if (entries.length === 0) return 'defaults';
  return entries
    .map(([key, value]) => `${key}=${typeof value === 'object' ? '{…}' : String(value)}`)
    .join('  ');
}

/** Builds a processing pipeline step by step, rendering each step's inputs
 * from the backend's algorithm catalog.
 *
 * Presented as a vertical stepper because step order is scientifically
 * load-bearing (despiking after normalization is a different — wrong —
 * result). Only one step's param form is expanded at a time; the rest
 * collapse to a summary line, so a five-step pipeline reads as five lines,
 * not five forms.
 *
 * The pipeline is edited as a local draft and committed in one action,
 * rather than writing a ledger per edit. Ledgers are immutable and
 * content-addressed, so per-edit writes would litter the table with a row
 * for every intermediate pipeline a user clicked through on the way to the
 * one they meant. */
export default function PipelineBuilder({ spectrum, onApplied }: Props) {
  const [catalog, setCatalog] = useState<AlgorithmCatalog | null>(null);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [steps, setSteps] = useState<DraftStep[]>([]);
  const [picked, setPicked] = useState('');
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<number | null>(null);

  useEffect(() => {
    getAlgorithmCatalog()
      .then(setCatalog)
      .catch((err) => setCatalogError(err instanceof Error ? err.message : String(err)));
  }, []);

  const savedSteps = useMemo<DraftStep[]>(
    () =>
      (spectrum.current_ledger?.steps ?? []).map((s) => ({
        type: s.type,
        params: { ...s.params },
      })),
    [spectrum.current_ledger],
  );

  useEffect(() => {
    setSteps(savedSteps);
    setExpanded(null);
  }, [savedSteps]);

  const byType = useMemo(() => {
    const map = new Map<string, AlgorithmInfo>();
    for (const algorithm of catalog?.algorithms ?? []) map.set(algorithm.step_type, algorithm);
    return map;
  }, [catalog]);

  const dirty = JSON.stringify(steps) !== JSON.stringify(savedSteps);

  function addStep() {
    const algorithm = byType.get(picked);
    if (!algorithm) return;
    setSteps([...steps, { type: algorithm.step_type, params: defaultParamsFor(algorithm) }]);
    setExpanded(steps.length); // open the new step's form
    setPicked('');
  }

  function updateParam(index: number, key: string, value: unknown) {
    setSteps(
      steps.map((step, i) => {
        if (i !== index) return step;
        const params = { ...step.params };
        // Dropping the key entirely, rather than sending null, is what lets
        // an emptied optional field fall back to the algorithm's own default
        // instead of failing its type check.
        if (value === undefined) delete params[key];
        else params[key] = value;
        return { ...step, params };
      }),
    );
  }

  function move(index: number, delta: number) {
    const target = index + delta;
    if (target < 0 || target >= steps.length) return;
    const reordered = [...steps];
    [reordered[index], reordered[target]] = [reordered[target], reordered[index]];
    setSteps(reordered);
    if (expanded === index) setExpanded(target);
    else if (expanded === target) setExpanded(index);
  }

  function remove(index: number) {
    setSteps(steps.filter((_, i) => i !== index));
    if (expanded === index) setExpanded(null);
    else if (expanded !== null && expanded > index) setExpanded(expanded - 1);
  }

  async function apply() {
    if (!spectrum.raw_file_id) {
      setError('This spectrum has no raw file to attach a pipeline to.');
      return;
    }
    setError(null);
    setApplying(true);
    try {
      const { ledger_id } = await createLedger(
        spectrum.raw_file_id,
        steps.map((step, order) => ({ type: step.type, params: step.params, order })),
      );
      // Creating a ledger doesn't attach it — that's a separate, explicit
      // step, so a draft stays editable until its owner decides what
      // "current" means for them.
      const updated = await updateSpectrum(spectrum.id, { current_ledger_id: ledger_id });
      onApplied(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setApplying(false);
    }
  }

  if (catalogError) return <p className="error">Could not load algorithms: {catalogError}</p>;
  if (!catalog) return <Skeleton lines={3} height="2.5rem" />;

  return (
    <section>
      <h2>Processing pipeline</h2>

      {steps.length === 0 && (
        <p className="hint">
          No steps yet — the chart shows the raw spectrum. A typical Raman pipeline despikes,
          then suppresses the fluorescence background, then normalizes.
        </p>
      )}

      <ol className={steps.length > 0 ? 'pipeline' : undefined}>
        {steps.map((step, index) => {
          const algorithm = byType.get(step.type);
          const properties = algorithm?.param_schema.properties ?? {};
          const required = algorithm?.param_schema.required ?? [];
          const isOpen = expanded === index;
          return (
            <li key={`${step.type}-${index}`} className="pipeline-step">
              <span className="pipeline-step__dot" aria-hidden="true">
                {index + 1}
              </span>
              <Card className="pipeline-step__card" title={undefined}>
                {/* The toggle and the step actions are siblings — a button
                    may not contain other buttons. */}
                <div className="pipeline-step__summary-row">
                  <button
                    type="button"
                    className="pipeline-step__summary"
                    aria-expanded={isOpen}
                    onClick={() => setExpanded(isOpen ? null : index)}
                  >
                    <span className="pipeline-step__label">{algorithm?.label ?? step.type}</span>
                    {algorithm && (
                      <span className={`cat-badge cat-badge--${algorithm.category}`}>
                        {CATEGORY_LABELS[algorithm.category] ?? algorithm.category}
                      </span>
                    )}
                    {!isOpen && (
                      <span className="pipeline-step__params-summary">
                        {paramsSummary(step.params)}
                      </span>
                    )}
                  </button>
                  <span className="pipeline-step__actions">
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => move(index, -1)}
                      disabled={index === 0}
                      aria-label="Move step up"
                    >
                      ↑
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => move(index, 1)}
                      disabled={index === steps.length - 1}
                      aria-label="Move step down"
                    >
                      ↓
                    </Button>
                    <Button size="sm" variant="danger" onClick={() => remove(index)}>
                      Remove
                    </Button>
                  </span>
                </div>

                {isOpen && (
                  <div className="pipeline-step__body">
                    {algorithm?.transforms_axis && (
                      <p className="hint">
                        Changes the wavenumber axis — steps after this one see the shortened
                        spectrum.
                      </p>
                    )}
                    {Object.keys(properties).length === 0 ? (
                      <p className="hint">No parameters.</p>
                    ) : (
                      Object.entries(properties).map(([key, property]) => (
                        <ParamField
                          key={key}
                          name={key}
                          property={property}
                          required={required.includes(key)}
                          value={step.params[key]}
                          onChange={(value) => updateParam(index, key, value)}
                          idPrefix={`step-${index}`}
                        />
                      ))
                    )}
                  </div>
                )}
              </Card>
            </li>
          );
        })}
      </ol>

      <div className="pipeline-add">
        <SelectField
          label="Add a step"
          value={picked}
          onChange={(e) => setPicked(e.target.value)}
          hint={picked ? byType.get(picked)?.description : undefined}
        >
          <option value="">Choose an algorithm...</option>
          {catalog.categories.map((category) => (
            <optgroup key={category} label={CATEGORY_LABELS[category] ?? category}>
              {catalog.algorithms
                .filter((a) => a.category === category)
                .map((a) => (
                  <option key={a.step_type} value={a.step_type}>
                    {a.label}
                  </option>
                ))}
            </optgroup>
          ))}
        </SelectField>
        <Button onClick={addStep} disabled={!picked}>
          Add step
        </Button>
      </div>

      <div className="pipeline-commit">
        <Button variant="primary" onClick={apply} disabled={!dirty} loading={applying}>
          Apply pipeline
        </Button>
        <Button variant="ghost" onClick={() => setSteps(savedSteps)} disabled={!dirty || applying}>
          Discard changes
        </Button>
        {dirty && <span className="hint">Unsaved changes</span>}
      </div>

      {error && <p className="error">{error}</p>}
    </section>
  );
}
