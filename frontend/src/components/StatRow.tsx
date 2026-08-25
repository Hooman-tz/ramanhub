import { Link } from 'react-router-dom';

export interface Stat {
  label: string;
  value: number | string;
  /** Where this number came from. Every count should be clickable through to
   * the thing it counts — a number with no destination is one the reader has
   * to take on faith. */
  to?: string;
  /** One line explaining exactly what is counted. These figures are public
   * and comparable, so what they exclude matters as much as what they
   * include. */
  title?: string;
}

/** A row of headline numbers. Scoped to `.stats` rather than reusing the
 * existing `.stat-row` class, which is generic and shared with other pages —
 * restyling that one has blast radius well beyond the profile. */
export default function StatRow({ stats }: { stats: Stat[] }) {
  return (
    <dl className="stats">
      {stats.map((stat) => (
        <div key={stat.label} className="stats__item" title={stat.title}>
          <dt>{stat.label}</dt>
          <dd>
            {stat.to ? <Link to={stat.to}>{stat.value}</Link> : stat.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}
