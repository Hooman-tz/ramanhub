import type { ButtonHTMLAttributes } from 'react';
import Spinner from './Spinner';

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** primary = solid accent pill (one per view, the main action);
   *  glass = secondary; ghost = tertiary/inline; danger = destructive. */
  variant?: 'primary' | 'glass' | 'ghost' | 'danger';
  size?: 'md' | 'sm';
  /** Shows an inline spinner and disables the button — for in-flight
   * actions, replacing the "Uploading..." label-swap pattern. */
  loading?: boolean;
}

export default function Button({
  variant = 'glass',
  size = 'md',
  loading = false,
  disabled,
  children,
  className,
  type = 'button',
  ...rest
}: Props) {
  const classes = [
    'ui-button',
    `ui-button--${variant}`,
    size === 'sm' && 'ui-button--sm',
    className,
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <button type={type} className={classes} disabled={disabled || loading} {...rest}>
      {loading && <Spinner />}
      {children}
    </button>
  );
}
