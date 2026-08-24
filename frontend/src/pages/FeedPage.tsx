import { useCallback, useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { getFeed, type FeedItem, type FeedOptions } from '../api/findings';
import FeedCard from '../components/FeedCard';
import { Button, Card, EmptyState, Skeleton } from '../components/ui';

const PAGE_SIZE = 20;

const KIND_FILTERS: Array<{ value: NonNullable<FeedOptions['kind']>; label: string }> = [
  { value: 'all', label: 'Everything' },
  { value: 'findings', label: 'Findings' },
  { value: 'spectra', label: 'Spectra' },
];

export default function FeedPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [items, setItems] = useState<FeedItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [exhausted, setExhausted] = useState(false);

  const kind = (searchParams.get('kind') as FeedOptions['kind']) ?? 'all';
  const tag = searchParams.get('tag') ?? '';
  const author = searchParams.get('author') ?? '';
  const verifiedOnly = searchParams.get('trust_tier') === 'doi_verified';

  const options: FeedOptions = {
    kind,
    tag: tag || undefined,
    author: author || undefined,
    trust_tier: verifiedOnly ? 'doi_verified' : undefined,
  };

  const load = useCallback(
    (offset: number) => {
      const first = offset === 0;
      if (first) setLoading(true);
      else setLoadingMore(true);
      setError(null);

      getFeed({ ...options, limit: PAGE_SIZE, offset })
        .then((page) => {
          setItems((current) => (first ? page : [...current, ...page]));
          // A short page means there's nothing after it — cheaper than a
          // count query, and correct as long as the page size is fixed.
          setExhausted(page.length < PAGE_SIZE);
        })
        .catch((err) => setError(err instanceof Error ? err.message : String(err)))
        .finally(() => {
          setLoading(false);
          setLoadingMore(false);
        });
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [kind, tag, author, verifiedOnly],
  );

  useEffect(() => {
    load(0);
  }, [load]);

  function setFilter(key: string, value: string | null) {
    const next = new URLSearchParams(searchParams);
    if (value) next.set(key, value);
    else next.delete(key);
    setSearchParams(next, { replace: true });
  }

  return (
    <div className="feed-page">
      <header className="page-head">
        <div>
          <h1>Feed</h1>
          <p className="hint">
            What the community is publishing and discussing. Ranked by a blend of
            engagement, recency and peer-reviewed status — switch to{' '}
            <Link to="/search">Search</Link> when you know what you're looking for.
          </p>
        </div>
        {/* A Link styled as the primary action: it navigates, so it must
            stay an anchor (middle-click, open-in-new-tab, copy link all
            break on a button that calls navigate()). */}
        <Link to="/findings/new" className="ui-button ui-button--primary">
          Write a finding
        </Link>
      </header>

      <div className="filter-bar" role="group" aria-label="Feed filters">
        <div className="segmented" role="group" aria-label="Content type">
          {KIND_FILTERS.map((option) => (
            <button
              key={option.value}
              type="button"
              className="segmented__option"
              aria-pressed={kind === option.value}
              onClick={() => setFilter('kind', option.value === 'all' ? null : option.value)}
            >
              {option.label}
            </button>
          ))}
        </div>

        <label className="checkbox">
          <input
            type="checkbox"
            checked={verifiedOnly}
            onChange={(e) => setFilter('trust_tier', e.target.checked ? 'doi_verified' : null)}
          />
          DOI-verified only
        </label>

        {(tag || author) && (
          <div className="active-filters">
            {tag && (
              <button type="button" className="tag tag--removable" onClick={() => setFilter('tag', null)}>
                tag: {tag} ×
              </button>
            )}
            {author && (
              <button
                type="button"
                className="tag tag--removable"
                onClick={() => setFilter('author', null)}
              >
                by: {author} ×
              </button>
            )}
          </div>
        )}
      </div>

      {error && <p className="error">{error}</p>}

      {loading ? (
        <div className="feed-list">
          {[0, 1, 2].map((i) => (
            <Card key={i}>
              <Skeleton lines={4} />
            </Card>
          ))}
        </div>
      ) : items.length === 0 ? (
        <EmptyState title="Nothing here yet">
          <p className="hint">
            {tag || author || verifiedOnly
              ? 'No published work matches these filters. Try clearing one.'
              : 'Nobody has published yet. Upload a spectrum, process it and publish it — or write the first finding.'}
          </p>
        </EmptyState>
      ) : (
        <>
          <div className="feed-list">
            {items.map((item) => (
              <FeedCard key={`${item.kind}-${item.id}`} item={item} />
            ))}
          </div>
          {!exhausted && (
            <div className="feed-more">
              <Button onClick={() => load(items.length)} loading={loadingMore}>
                Load more
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
