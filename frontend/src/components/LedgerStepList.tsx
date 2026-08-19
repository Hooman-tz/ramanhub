import type { LedgerStep } from '../api/client';

export default function LedgerStepList({ steps }: { steps: LedgerStep[] | undefined }) {
  if (!steps || steps.length === 0) {
    return <p>No processing steps yet.</p>;
  }

  return (
    <ol>
      {steps.map((step, i) => (
        <li key={i}>
          <strong>{step.type}</strong> (v{step.version})
          <pre>{JSON.stringify(step.params, null, 2)}</pre>
        </li>
      ))}
    </ol>
  );
}
