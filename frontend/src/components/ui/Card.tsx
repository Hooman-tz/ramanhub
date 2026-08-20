import type { HTMLAttributes, ReactNode } from 'react';

// `title` here is a heading node, not the native tooltip attribute — omit
// the DOM prop so the wider ReactNode type doesn't clash with it.
interface Props extends Omit<HTMLAttributes<HTMLElement>, 'title'> {
  title?: ReactNode;
  /** strong = higher-opacity glass for surfaces that need to sit above
   * other glass (modals-in-effect like the DOI preview). */
  strong?: boolean;
}

/** Glass content panel — the standard elevated surface. */
export default function Card({ title, strong, children, className, ...rest }: Props) {
  const classes = ['glass-panel', strong && 'glass-panel--strong', 'ui-card', className]
    .filter(Boolean)
    .join(' ');
  return (
    <section className={classes} {...rest}>
      {title !== undefined && <h2 className="ui-card__title">{title}</h2>}
      {children}
    </section>
  );
}
