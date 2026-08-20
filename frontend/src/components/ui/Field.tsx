import type {
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
} from 'react';
import { useId } from 'react';

interface FieldChrome {
  label: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  /** Fields default to a 420px reading width; set full for editors that
   * want the whole column (comment boxes, JSON params). */
  full?: boolean;
}

function FieldShell({
  label,
  hint,
  error,
  full,
  id,
  children,
}: FieldChrome & { id: string; children: ReactNode }) {
  return (
    <div className={full ? 'ui-field ui-field--full' : 'ui-field'}>
      <label className="ui-field__label" htmlFor={id}>
        {label}
      </label>
      {children}
      {error ? (
        <p className="ui-field__error">{error}</p>
      ) : (
        hint && <p className="ui-field__hint">{hint}</p>
      )}
    </div>
  );
}

type InputProps = FieldChrome & InputHTMLAttributes<HTMLInputElement>;

export function InputField({ label, hint, error, full, id, ...rest }: InputProps) {
  const autoId = useId();
  const fieldId = id ?? autoId;
  return (
    <FieldShell label={label} hint={hint} error={error} full={full} id={fieldId}>
      <input id={fieldId} {...rest} />
    </FieldShell>
  );
}

type SelectProps = FieldChrome & SelectHTMLAttributes<HTMLSelectElement>;

export function SelectField({ label, hint, error, full, id, children, ...rest }: SelectProps) {
  const autoId = useId();
  const fieldId = id ?? autoId;
  return (
    <FieldShell label={label} hint={hint} error={error} full={full} id={fieldId}>
      <select id={fieldId} {...rest}>
        {children}
      </select>
    </FieldShell>
  );
}

type TextareaProps = FieldChrome & TextareaHTMLAttributes<HTMLTextAreaElement>;

export function TextareaField({ label, hint, error, full, id, ...rest }: TextareaProps) {
  const autoId = useId();
  const fieldId = id ?? autoId;
  return (
    <FieldShell label={label} hint={hint} error={error} full={full} id={fieldId}>
      <textarea id={fieldId} {...rest} />
    </FieldShell>
  );
}
