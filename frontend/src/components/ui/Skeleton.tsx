import type { CSSProperties } from 'react';

interface Props {
  width?: CSSProperties['width'];
  height?: CSSProperties['height'];
  /** Stack count — renders N bars with a small gap, for list placeholders. */
  lines?: number;
}

/** Shimmering loading placeholder — replaces bare "Loading..." text so
 * in-flight views keep their layout instead of collapsing to a sentence. */
export default function Skeleton({ width = '100%', height = '1rem', lines = 1 }: Props) {
  return (
    <div aria-busy="true" aria-live="polite">
      {Array.from({ length: lines }, (_, i) => (
        <div
          key={i}
          className="ui-skeleton"
          style={{ width, height, marginBottom: lines > 1 ? 'var(--sp-2)' : undefined }}
        />
      ))}
    </div>
  );
}
