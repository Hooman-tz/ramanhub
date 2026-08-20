interface Props {
  /** Spectrum lifecycle states map to the semantic scales; `neutral` is the
   * fallback for anything unrecognized. */
  state: 'draft' | 'published' | 'embargoed' | string;
}

const KNOWN = new Set(['draft', 'published', 'embargoed']);

export default function Badge({ state }: Props) {
  const variant = KNOWN.has(state) ? state : 'draft';
  return <span className={`badge ${variant}`}>{state}</span>;
}
