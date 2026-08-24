import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { getPublicProfile, type PublicProfile } from '../api/client';
import { getFeed, type FeedItem } from '../api/findings';
import FeedCard from '../components/FeedCard';
import { Card, EmptyState, Skeleton } from '../components/ui';

function initials(name: string): string {
  return name
    .split(/\s+/)
    .map((part) => part[0])
    .filter(Boolean)
    .slice(0, 2)
    .join('')
    .toUpperCase();
}

/** A contributor's public page — what a DOI, a citation or a feed byline
 * points at. Shows published work only: counts and listings of someone's
 * drafts would leak how much unpublished work they have, which is exactly
 * what the draft/published split exists to keep private. */
export default function ProfilePage() {
  const { handle } = useParams<{ handle: string }>();
  const [profile, setProfile] = useState<PublicProfile | null>(null);
  const [items, setItems] = useState<FeedItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!handle) return;
    setLoading(true);
    setError(null);
    getPublicProfile(handle)
      .then(setProfile)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setLoading(false));
    getFeed({ author: handle, limit: 50 })
      .then(setItems)
      .catch(() => {});
  }, [handle]);

  if (loading) return <Skeleton lines={5} height="2rem" />;
  if (error || !profile) {
    return (
      <EmptyState title="Profile not found">
        <p className="hint">
          No contributor with the handle “{handle}”. <Link to="/feed">Back to the feed</Link>.
        </p>
      </EmptyState>
    );
  }

  const name = profile.display_name ?? profile.handle ?? 'Contributor';

  return (
    <div className="profile">
      <header className="profile__head">
        {profile.avatar_url ? (
          <img src={profile.avatar_url} alt="" className="profile__avatar" />
        ) : (
          <span className="profile__avatar">{initials(name)}</span>
        )}
        <div>
          <h1>{name}</h1>
          {profile.handle && <p className="profile__handle">@{profile.handle}</p>}
          {profile.affiliation && <p className="hint">{profile.affiliation}</p>}
          {profile.orcid_id && (
            <p>
              <a
                href={`https://orcid.org/${profile.orcid_id}`}
                target="_blank"
                rel="noreferrer noopener"
                className="orcid-link"
              >
                ORCID {profile.orcid_id}
              </a>
            </p>
          )}
        </div>
      </header>

      {profile.bio && <p className="profile__bio">{profile.bio}</p>}

      <Card>
        <dl className="stat-row">
          <div>
            <dt>Published spectra</dt>
            <dd>{profile.spectrum_count}</dd>
          </div>
          <div>
            <dt>Findings</dt>
            <dd>{profile.finding_count}</dd>
          </div>
          <div>
            <dt>Member since</dt>
            <dd>{new Date(profile.created_at).getFullYear()}</dd>
          </div>
        </dl>
      </Card>

      <h2>Published work</h2>
      {items.length === 0 ? (
        <EmptyState title="Nothing published yet">
          <p className="hint">This contributor hasn't published anything publicly.</p>
        </EmptyState>
      ) : (
        <div className="feed-list">
          {items.map((item) => (
            <FeedCard key={`${item.kind}-${item.id}`} item={item} />
          ))}
        </div>
      )}
    </div>
  );
}
