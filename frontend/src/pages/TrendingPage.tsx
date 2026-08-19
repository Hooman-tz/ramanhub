import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { getTrending, type TrendingItem } from '../api/social';

const WINDOW_OPTIONS = [1, 7, 30];

export default function TrendingPage() {
  const [items, setItems] = useState<TrendingItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [windowDays, setWindowDays] = useState(7);

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [windowDays]);

  function refresh() {
    setLoading(true);
    setError(null);
    getTrending({ window_days: windowDays })
      .then(setItems)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setLoading(false));
  }

  return (
    <div>
      <h1>Trending</h1>
      <p className="hint">
        Ranked by upvotes in the trailing window. This is a separate feed from
        Search — it never affects core search ranking.
      </p>

      <div className="field-row">
        <label htmlFor="window-days">Window</label>
        <select
          id="window-days"
          value={windowDays}
          onChange={(e) => setWindowDays(Number(e.target.value))}
        >
          {WINDOW_OPTIONS.map((d) => (
            <option key={d} value={d}>
              Last {d} day{d === 1 ? '' : 's'}
            </option>
          ))}
        </select>
      </div>

      {error && <p className="error">{error}</p>}
      {loading && <p>Loading trending spectra...</p>}
      {!loading && items.length === 0 && <p>Nothing trending yet.</p>}

      <ol>
        {items.map((item) => (
          <li key={item.id}>
            <Link to={`/spectra/${item.id}`}>{item.title ?? `Spectrum ${item.id}`}</Link>
            {' — '}
            {item.vote_count} vote{item.vote_count === 1 ? '' : 's'}
          </li>
        ))}
      </ol>
    </div>
  );
}
