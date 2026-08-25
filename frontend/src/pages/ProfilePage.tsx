import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { getPins, getPublicProfile, type PinnedItem, type PublicProfile } from '../api/client';
import { getFeed, type FeedItem } from '../api/findings';
import { useAuth } from '../auth/useAuth';
import FeedCard from '../components/FeedCard';
import FollowButton from '../components/FollowButton';
import SpectrumThumb from '../components/SpectrumThumb';
import ContributionChart from '../components/ContributionChart';
import StatRow, { type Stat } from '../components/StatRow';
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

const TABS = [
  { id: 'overview', label: 'Overview' },
  { id: 'findings', label: 'Findings' },
  { id: 'spectra', label: 'Spectra' },
] as const;

type TabId = (typeof TABS)[number]['id'];

export default function ProfilePage() {
  const { handle } = useParams<{ handle: string }>();
  const { user } = useAuth();
  const [params, setParams] = useSearchParams();

  const [profile, setProfile] = useState<PublicProfile | null>(null);
  const [items, setItems] = useState<FeedItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [itemsLoading, setItemsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [followers, setFollowers] = useState<number | null>(null);
  const [pins, setPins] = useState<PinnedItem[]>([]);

  const tab = (params.get('tab') as TabId) ?? 'overview';
  const isSelf = Boolean(user && profile && user.id === profile.id);

  useEffect(() => {
    if (!handle) return;
    setLoading(true);
    setError(null);
    getPublicProfile(handle)
      .then((p) => {
        setProfile(p);
        setFollowers(p.followers);
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setLoading(false));
  }, [handle]);

  useEffect(() => {
    if (!handle) return;
    setItemsLoading(true);
    // Findings before spectra everywhere: a Finding is the interpreted,
    // citable unit, which is what a visitor is actually evaluating. A wall of
    // 400 spectra is a database dump, not an identity.
    const kind = tab === 'spectra' ? 'spectra' : tab === 'findings' ? 'findings' : 'all';
    getFeed({ author: handle, kind, limit: 50 })
      .then(setItems)
      .catch(() => setItems([]))
      .finally(() => setItemsLoading(false));
  }, [handle, tab]);

  useEffect(() => {
    if (!handle) return;
    // Pins are decoration on someone else's page — a failure here must not
    // take the profile down, so it swallows rather than setting `error`.
    getPins(handle).then(setPins).catch(() => setPins([]));
  }, [handle]);

  const onFollowersChange = useCallback((count: number) => setFollowers(count), []);

  const stats = useMemo<Stat[]>(() => {
    if (!profile) return [];
    const h = profile.handle ?? '';
    return [
      {
        label: 'Spectra',
        value: profile.spectrum_count,
        to: `/u/${h}?tab=spectra`,
        title: 'Published spectra. Drafts are never counted publicly.',
      },
      {
        label: 'Findings',
        value: profile.finding_count,
        to: `/u/${h}?tab=findings`,
        title: 'Published Findings — the citable, interpreted unit.',
      },
      {
        label: 'Reuses',
        value: profile.reuse_findings,
        title:
          `Used in ${profile.reuse_findings} Finding(s) by ${profile.reuse_groups} other ` +
          'contributor(s). Excludes Findings you wrote about your own data — ' +
          'reuse has to be earned by other people.',
      },
      {
        label: 'Followers',
        value: followers ?? profile.followers,
        title: 'People following this contributor.',
      },
      {
        label: 'Votes',
        value: profile.votes_received,
        title: 'Upvotes received across published spectra and Findings.',
      },
      {
        label: 'Shares',
        value: profile.shares_received,
        title: 'Times others re-broadcast this work to their followers.',
      },
      {
        label: 'DOI-linked',
        value: profile.doi_linked,
        title: 'Published work linked to a real publication — externally verifiable.',
      },
      {
        label: 'Since',
        value: new Date(profile.created_at).getFullYear(),
      },
    ];
  }, [profile, followers]);

  if (loading) return <Skeleton lines={5} height="2rem" />;
  if (error) return <p className="error">{error}</p>;
  if (!profile) return <p>Profile not found.</p>;

  const name = profile.display_name ?? profile.handle ?? 'Contributor';
  const hasAnything = profile.spectrum_count + profile.finding_count > 0;

  return (
    <div className="profile">
      <header className="profile__head">
        {profile.avatar_url ? (
          <img src={profile.avatar_url} alt="" className="profile__avatar" />
        ) : (
          <span className="profile__avatar">{initials(name)}</span>
        )}
        <div className="profile__identity">
          <h1>{name}</h1>
          {profile.handle && <p className="profile__handle">@{profile.handle}</p>}
          {profile.affiliation && <p className="hint">{profile.affiliation}</p>}
          {profile.orcid_id && (
            <p className="profile__orcid">
              <a
                href={`https://orcid.org/${profile.orcid_id}`}
                target="_blank"
                rel="noreferrer noopener"
                className="orcid-link"
              >
                ORCID {profile.orcid_id}
              </a>{' '}
              {/* No badge. The iD is free text with no verification flow
                  behind it, so anyone could enter anyone's — labelling it
                  "verified" would make this field an impersonation tool. */}
              <span className="chip chip--muted" title="We don't verify ORCID iDs yet.">
                self-reported
              </span>
            </p>
          )}
        </div>
        <div className="profile__actions">
          {profile.handle && (
            <FollowButton
              handle={profile.handle}
              isSelf={isSelf}
              signedIn={Boolean(user && !user.is_guest)}
              onCountChange={onFollowersChange}
            />
          )}
          {isSelf && (
            <Link to="/settings" className="ui-button ui-button--sm">
              Edit profile
            </Link>
          )}
        </div>
      </header>

      {profile.bio && <p className="profile__bio">{profile.bio}</p>}

      <Card>
        <StatRow stats={stats} />
      </Card>

      {tab === 'overview' && pins.length > 0 && (
        <>
          {/* Curated, and therefore above the recency-ordered list below:
              the work someone wants to be known for is often not the thing
              they touched most recently. */}
          <h2>Pinned</h2>
          <div className="pins">
            {pins.map((pin) => (
              <Link
                key={`${pin.kind}-${pin.id}`}
                to={
                  pin.kind === 'finding'
                    ? `/findings/${pin.id}`
                    : pin.accession
                      ? `/s/${pin.accession}`
                      : `/spectra/${pin.id}`
                }
                className="pins__item"
              >
                <span className="pins__title">{pin.title ?? 'Untitled'}</span>
                <span className="pins__meta">{pin.accession ?? pin.kind}</span>
              </Link>
            ))}
          </div>
        </>
      )}

      {tab === 'overview' && profile.handle && <ContributionChart handle={profile.handle} />}

      <nav className="profile__tabs" aria-label="Profile sections">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            className={t.id === tab ? 'profile__tab is-active' : 'profile__tab'}
            aria-current={t.id === tab ? 'page' : undefined}
            onClick={() => setParams(t.id === 'overview' ? {} : { tab: t.id })}
          >
            {t.label}
            {t.id === 'findings' && <span className="profile__tab-count">{profile.finding_count}</span>}
            {t.id === 'spectra' && <span className="profile__tab-count">{profile.spectrum_count}</span>}
          </button>
        ))}
      </nav>

      {itemsLoading ? (
        <Skeleton lines={3} height="4rem" />
      ) : items.length > 0 ? (
        tab === 'spectra' ? (
          /* Spectra get a grid of previews rather than a list of cards.
             Every tile is rendered by the server over the SAME wavenumber
             window, so peak positions line up column-for-column across tiles
             — which is the only reason a wall of visually near-identical
             spectra is scannable at all. */
          <div className="thumb-grid">
            {items.map((item) => (
              <Link
                key={item.id}
                to={item.accession ? `/s/${item.accession}` : `/spectra/${item.id}`}
                className="thumb-grid__item"
              >
                <SpectrumThumb spectrumId={item.id} label={item.title ?? item.material_type} />
                <span className="thumb-grid__caption">
                  {item.title ?? item.material_type ?? 'Untitled'}
                </span>
              </Link>
            ))}
          </div>
        ) : (
          <div className="feed-list">
            {items.map((item) => (
              <FeedCard key={`${item.kind}-${item.id}`} item={item} />
            ))}
          </div>
        )
      ) : isSelf && !hasAnything ? (
        /* The owner's own empty profile is the highest-leverage screen here.
           Showing them "0 / 0 / 0" tells a new user the place is empty and
           they are nobody; a checklist tells them what to do next. */
        <Card title="Your profile is empty — here's how to fill it">
          <ol className="profile__checklist">
            <li>
              <Link to="/upload">Upload your first spectrum</Link> — drag a vendor file in;
              no format conversion needed.
            </li>
            <li>Run <strong>Auto-clean</strong> on it to see the processing tools work.</li>
            <li>Publish it, and it gets a citable accession like <code>RH-S-000042</code>.</li>
            <li>
              <Link to="/findings/new">Write a Finding</Link> — bundle spectra, analyses and a
              DOI into something people can cite.
            </li>
          </ol>
          {!profile.bio && (
            <p className="hint">
              Also worth 30 seconds: <Link to="/settings">add a bio and your affiliation</Link>{' '}
              so people know what you work on.
            </p>
          )}
        </Card>
      ) : (
        <EmptyState title="Nothing published yet">
          {profile.handle && !isSelf && (
            <p className="hint">
              Follow @{profile.handle} to see their work when it lands.
            </p>
          )}
        </EmptyState>
      )}
    </div>
  );
}
