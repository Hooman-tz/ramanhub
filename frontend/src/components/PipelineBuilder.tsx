import { useEffect, useMemo, useState } from 'react';
import { createLedger, updateSpectrum, type Spectrum } from '../api/client';
import { previewPipeline, type SpectrumData } from '../api/visualization';
import { useHistory } from '../lib/useHistory';
import {
  CATEGORY_LABELS,
  defaultParamsFor,
  getAlgorithmCatalog,
  type AlgorithmCatalog,
  type AlgorithmInfo,
} from '../api/processing';
import ParamField from './ParamField';
import { Button, Card, SelectField, Skeleton } from './ui';

/** How long the pipeline must sit unchanged before a preview is requested.
 * Longer than the palette's 200ms: a preview replays real numerics on the
 * server, so firing one per slider pixel would be wasteful in a way a
 * metadata query isn't. Short enough to still feel like a response to the
 * edit rather than a separate event. */
const PREVIEW_DEBOUNCE_MS = 400;

interface DraftStep {
  type: string;
  params: Record<string, unknown>;
}

interface Props {
  spectrum: Spectrum;
  onApplied: (spectrum: Spectrum) => void;
  /** Receives the uncommitted curve for the draft pipeline, or `null` when
   * the draft matches what's saved (nothing to preview) or the preview
   * failed. MUST be referentially stable — wrap it in useCallback — or the
   * debounce effect below re-subscribes every render and never settles. */
  onPreview?: (data: SpectrumData | null) => void;
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
/** One-click starting pipelines.
 *
 * The order is load-bearing and is the main thing a newcomer gets wrong:
 * despike FIRST (a cosmic ray corrupts every fit that follows it), smooth
 * before baseline estimation, then subtract the background, then normalize
 * last — normalizing before background removal scales the background rather
 * than the bands.
 *
 * Parameters are left at each algorithm's own defaults rather than tuned
 * here, so a preset is exactly "the standard steps in the standard order"
 * and stays honest when an algorithm's defaults improve. */
const PRESETS: Array<{
  id: string;
  label: string;
  hint: string;
  steps: string[];
}> = [
  {
    id: 'auto-clean',
    label: 'Auto-clean',
    hint: 'Despike, smooth, remove the fluorescence background, then SNV. The standard '
      + 'starting point for most Raman data.',
    steps: [
      'raman.despike',
      'raman.smooth.savitzky_golay',
      'raman.fluorescence_suppression.airpls',
      'raman.snv',
    ],
  },
  {
    id: 'baseline-only',
    label: 'Baseline only',
    hint: 'Just remove the fluorescence background, leaving intensities otherwise as '
      + 'measured — when absolute scale matters.',
    steps: ['raman.fluorescence_suppression.airpls'],
  },
  {
    id: 'compare-ready',
    label: 'Compare-ready',
    hint: 'Despike, baseline, then vector normalize — the geometry the similarity '
      + 'search uses, so results are directly comparable.',
    steps: [
      'raman.despike',
      'raman.fluorescence_suppression.airpls',
      'raman.normalize.vector',
    ],
  },
];

export default function PipelineBuilder({ spectrum, onApplied, onPreview }: Props) {
  const [catalog, setCatalog] = useState<AlgorithmCatalog | null>(null);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const history = useHistory<DraftStep[]>([]);
  const steps = history.state;
  const setSteps = history.set;
  const [picked, setPicked] = useState('');
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);

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
    // reset, not set: undoing across a save would restore edits the server no
    // longer knows about, leaving this form and the server disagreeing.
    history.reset(savedSteps);
    setExpanded(null);
    // `history` is a fresh object every render by construction; depending on
    // it here would loop. `reset` itself is stable (useCallback).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [savedSteps, history.reset]);

  const byType = useMemo(() => {
    const map = new Map<string, AlgorithmInfo>();
    for (const algorithm of catalog?.algorithms ?? []) map.set(algorithm.step_type, algorithm);
    return map;
  }, [catalog]);

  const dirty = JSON.stringify(steps) !== JSON.stringify(savedSteps);

  // Live preview of the uncommitted pipeline. Debounced and guarded against
  // out-of-order responses: an earlier, slower preview must not overwrite the
  // curve for a later edit, which on a chart shows up as the plot flicking
  // back to a pipeline the user has already moved past.
  useEffect(() => {
    if (!onPreview) return;
    if (!dirty) {
      setPreviewError(null);
      onPreview(null);
      return;
    }
    let stale = false;
    const handle = setTimeout(() => {
      setPreviewing(true);
      previewPipeline(
        spectrum.id,
        steps.map((step, order) => ({ type: step.type, params: step.params, order })),
      )
        .then((data) => {
          if (stale) return;
          setPreviewError(null);
          onPreview(data);
        })
        .catch((err) => {
          if (stale) return;
          // A 422 here is informative, not a failure state: it means this
          // pipeline can't run on THIS spectrum, which is exactly what the
          // user needs to know before pressing Apply.
          setPreviewError(err instanceof Error ? err.message : String(err));
          onPreview(null);
        })
        .finally(() => {
          if (!stale) setPreviewing(false);
        });
    }, PREVIEW_DEBOUNCE_MS);
    return () => {
      stale = true;
      clearTimeout(handle);
    };
  }, [steps, dirty, spectrum.id, onPreview]);

  // ⌘Z / ⇧⌘Z. Skipped while a form field has focus so the browser's own
  // text undo keeps working inside a parameter input — stealing that would
  // be worse than not having the shortcut.
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (!(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== 'z') return;
      const target = event.target as HTMLElement | null;
      if (target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return;
      event.preventDefault();
      if (event.shiftKey) history.redo();
      else history.undo();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [history]);

  function applyPreset(presetId: string) {
    const preset = PRESETS.find((p) => p.id === presetId);
    if (!preset || !catalog) return;
    // Skip any step this backend doesn't ship rather than failing the whole
    // preset — the catalog is the source of truth for what exists.
    const built = preset.steps
      .map((type) => catalog.algorithms.find((a) => a.step_type === type))
      .filter((algorithm): algorithm is NonNullable<typeof algorithm> => Boolean(algorithm))
      .map((algorithm) => ({
        type: algorithm.step_type,
        params: defaultParamsFor(algorithm),
      }));
    setSteps(built);
    setExpanded(null);
  }

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
      // Coalesce every keystroke in one field into a single undo entry —
      // otherwise Ctrl-Z walks back one character at a time.
      `param:${index}:${key}`,
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
          No steps yet — the chart shows the raw spectrum. Start from a preset below, or
          build a pipeline step by step.
        </p>
      )}

      <div className="presets">
        <span className="presets__label">Start from</span>
        {PRESETS.map((preset) => (
          <button
            key={preset.id}
            type="button"
            className="ui-button ui-button--sm"
            title={preset.hint}
            onClick={() => applyPreset(preset.id)}
          >
            {preset.label}
          </button>
        ))}
      </div>
      <p className="hint presets__hint">
        A preset fills in the steps; nothing is committed until you press Apply, and every
        parameter stays editable.
      </p>

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
        <span className="pipeline-commit__history">
          <Button
            size="sm"
            variant="ghost"
            onClick={history.undo}
            disabled={!history.canUndo || applying}
            title="Undo (⌘Z)"
          >
            ↺ Undo
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={history.redo}
            disabled={!history.canRedo || applying}
            title="Redo (⇧⌘Z)"
          >
            ↻ Redo
          </Button>
        </span>
        <Button variant="ghost" onClick={() => setSteps(savedSteps)} disabled={!dirty || applying}>
          Discard changes
        </Button>
        {dirty && (
          <span className={previewError ? 'error' : 'hint'}>
            {previewError
              ? "This pipeline can't run on this spectrum — see below"
              : previewing
                ? 'Previewing…'
                : 'Previewing unsaved changes on the chart'}
          </span>
        )}
      </div>

      {previewError && (
        <p className="error">
          {previewError.replace(/^API error \d+:\s*/, '')}
        </p>
      )}

      {error && <p className="error">{error}</p>}
    </section>
  );
}
