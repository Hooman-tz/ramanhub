import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { getTrending, type TrendingItem } from '../api/social';
import { Card, EmptyState, SelectField, Skeleton } from '../components/ui';

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
    <div className="workspace-page">
      <header className="page-header">
        <div>
          <p className="eyebrow">Community signals</p>
          <h1>Trending spectra</h1>
          <p className="page-intro">Popular shared spectra, kept separate from objective scientific search results.</p>
        </div>
      </header>

      <div className="trending-toolbar">
        <SelectField
          id="window-days"
          label="Time window"
          value={windowDays}
          onChange={(e) => setWindowDays(Number(e.target.value))}
        >
          {WINDOW_OPTIONS.map((d) => (
            <option key={d} value={d}>
              Last {d} day{d === 1 ? '' : 's'}
            </option>
          ))}
        </SelectField>
      </div>

      {error && <p className="error">{error}</p>}
      {loading && <Skeleton lines={4} height="3rem" />}
      {!loading && items.length === 0 && <EmptyState title="Nothing is trending yet"><p>Community activity will appear here without changing search ranking.</p></EmptyState>}

      {items.length > 0 && <Card className="trending-list">
        <ol>
          {items.map((item, index) => (
            <li key={item.id}>
              <span className="trending-list__rank">{String(index + 1).padStart(2, '0')}</span>
              <Link to={`/spectra/${item.id}`}>{item.title ?? 'Untitled spectrum'}</Link>
              <span className="trending-list__votes">{item.vote_count} vote{item.vote_count === 1 ? '' : 's'}</span>
            </li>
          ))}
        </ol>
      </Card>}
    </div>
  );
}
