import type { LedgerStep } from '../api/client';

export default function LedgerStepList({ steps }: { steps: LedgerStep[] | undefined }) {
  if (!steps || steps.length === 0) {
    return <p className="hint">No transformations are applied. The displayed signal is the immutable raw spectrum.</p>;
  }

  return (
    <ol className="ledger-list">
      {steps.map((step, i) => (
        <li key={`${step.type}-${i}`} className="ledger-list__item">
          <span className="ledger-list__number">{String(i + 1).padStart(2, '0')}</span>
          <div>
            <strong>{step.type.replace(/^raman\./, '').split('.').join(' ')}</strong>
            <span className="ledger-list__version">Algorithm version {step.version}</span>
            {Object.keys(step.params).length > 0 && (
              <details>
                <summary>View parameters</summary>
                <pre>{JSON.stringify(step.params, null, 2)}</pre>
              </details>
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}
