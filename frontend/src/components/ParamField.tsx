import type { ParamProperty } from '../api/processing';

interface Props {
  name: string;
  property: ParamProperty;
  required: boolean;
  value: unknown;
  onChange: (value: unknown) => void;
  idPrefix: string;
}

/** One labelled input rendered from a JSON-Schema property.
 *
 * Numeric fields are deliberately kept as strings while being edited: a
 * spectroscopist typing "1e5" or "0." passes through states that
 * `Number()` maps to NaN or to a different value than they're aiming for,
 * and coercing on every keystroke fights the user. Conversion happens here
 * only when the text parses cleanly, and the raw text is passed up
 * otherwise so the field doesn't jump under them — the ledger POST is
 * what ultimately validates. */
export default function ParamField({
  name,
  property,
  required,
  value,
  onChange,
  idPrefix,
}: Props) {
  const id = `${idPrefix}-${name}`;
  const label = property.title ?? name;
  const isNumeric = property.type === 'number' || property.type === 'integer';

  return (
    <div className="field-row">
      <label htmlFor={id}>
        {label}
        {required && <span aria-hidden="true"> *</span>}
      </label>

      {property.type === 'boolean' ? (
        <input
          id={id}
          type="checkbox"
          checked={value === true}
          onChange={(e) => onChange(e.target.checked)}
        />
      ) : property.type === 'object' || property.type === 'array' ? (
        <textarea
          id={id}
          rows={3}
          placeholder='{"type": "array", "values": [...]}'
          value={value === undefined || value === '' ? '' : JSON.stringify(value)}
          onChange={(e) => {
            const text = e.target.value;
            if (text.trim() === '') {
              onChange(undefined);
              return;
            }
            try {
              onChange(JSON.parse(text));
            } catch {
              // Keep the half-typed text visible rather than discarding it;
              // the ledger POST rejects it if it never becomes valid JSON.
              onChange(text);
            }
          }}
        />
      ) : (
        <input
          id={id}
          type="text"
          inputMode={isNumeric ? 'decimal' : 'text'}
          value={value === undefined || value === null ? '' : String(value)}
          placeholder={
            property.default !== undefined ? `default ${String(property.default)}` : 'optional'
          }
          onChange={(e) => {
            const text = e.target.value;
            if (text === '') {
              onChange(undefined);
              return;
            }
            if (!isNumeric) {
              onChange(text);
              return;
            }
            const parsed = Number(text);
            onChange(Number.isFinite(parsed) ? parsed : text);
          }}
        />
      )}

      {property.description && <p className="hint">{property.description}</p>}
    </div>
  );
}
