import type { ReactNode } from 'react';

interface Props {
  title: string;
  children?: ReactNode;
}

/** Friendly zero-data placeholder — replaces bare "No results." paragraphs
 * so empty is a designed state, not an absence. */
export default function EmptyState({ title, children }: Props) {
  return (
    <div className="ui-empty">
      <p className="ui-empty__title">{title}</p>
      {children}
    </div>
  );
}
