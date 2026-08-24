import { Link } from 'react-router-dom';
import type { FeedItem } from '../api/findings';

function relativeTime(iso: string | null): string {
  if (!iso) return '';
  const then = new Date(iso).getTime();
  const seconds = Math.max(0, (Date.now() - then) / 1000);
  const units: Array<[number, Intl.RelativeTimeFormatUnit]> = [
    [60, 'second'],
    [3600, 'minute'],
    [86400, 'hour'],
    [2592000, 'day'],
    [31536000, 'month'],
  ];
  const formatter = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' });
  let previous = 1;
  for (const [limit, unit] of units) {
    if (seconds < limit) return formatter.format(-Math.floor(seconds / previous), unit);
    previous = limit;
  }
  return formatter.format(-Math.floor(seconds / 31536000), 'year');
}

function initials(name: string): string {
  return name
    .split(/\s+/)
    .map((part) => part[0])
    .filter(Boolean)
    .slice(0, 2)
    .join('')
    .toUpperCase();
}

export default function FeedCard({ item }: { item: FeedItem }) {
  const href = item.kind === 'finding' ? `/findings/${item.id}` : `/spectra/${item.id}`;
  const author = item.author;
  const authorName = author?.display_name ?? author?.handle ?? 'Unknown contributor';

  return (
    <article className="feed-card">
      <header className="feed-card__head">
        {author?.handle ? (
          <Link to={`/u/${author.handle}`} className="feed-card__author">
            {author.avatar_url ? (
              <img src={author.avatar_url} alt="" className="feed-card__avatar" />
            ) : (
              <span className="feed-card__avatar">{initials(authorName)}</span>
            )}
            <span>{authorName}</span>
          </Link>
        ) : (
          <span className="feed-card__author">
            <span className="feed-card__avatar">{initials(authorName)}</span>
            <span>{authorName}</span>
          </span>
        )}

        <span className="feed-card__meta">
          <span className={`chip chip--${item.kind}`}>
            {item.kind === 'finding' ? 'Finding' : 'Spectrum'}
          </span>
          {/* DOI presence is the trust tier — a peer-reviewed link, not a
              popularity signal. Shown here because it's the single most
              useful thing to know before opening a result. */}
          {item.doi && <span className="chip chip--verified">DOI-verified</span>}
          <time dateTime={item.published_at ?? undefined}>
            {relativeTime(item.published_at)}
          </time>
        </span>
      </header>

      <h3 className="feed-card__title">
        <Link to={href}>{item.title ?? item.accession ?? 'Untitled'}</Link>
      </h3>

      {item.summary && <p className="feed-card__summary">{item.summary}</p>}

      <div className="feed-card__facts">
        {item.accession && <code className="accession">{item.accession}</code>}
        {item.spectrum_count != null && item.spectrum_count > 0 && (
          <span>
            {item.spectrum_count} spectr{item.spectrum_count === 1 ? 'um' : 'a'}
          </span>
        )}
        {item.material_type && <span>{item.material_type}</span>}
        {item.snr != null && <span>SNR {item.snr.toFixed(1)}</span>}
      </div>

      {item.tags && item.tags.length > 0 && (
        <div className="feed-card__tags">
          {item.tags.map((tag) => (
            <Link key={tag} to={`/feed?tag=${encodeURIComponent(tag)}`} className="tag">
              {tag}
            </Link>
          ))}
        </div>
      )}

      <footer className="feed-card__footer">
        <span title="Upvotes">▲ {item.vote_count}</span>
        <span title="Comments">💬 {item.comment_count}</span>
      </footer>
    </article>
  );
}
