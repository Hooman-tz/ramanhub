import { useCallback, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  getFinding,
  getFindingVotes,
  listFindingComments,
  postFindingComment,
  toggleFindingVote,
  type Finding,
  type FindingComment,
} from '../api/findings';
import { useAuth } from '../auth/useAuth';
import FindingEntryView from '../components/FindingEntryView';
import { useToast } from '../components/Toast';
import { Button, Card, Skeleton } from '../components/ui';

export default function FindingPage() {
  const { id } = useParams<{ id: string }>();
  const { user } = useAuth();
  const { notify } = useToast();

  const [finding, setFinding] = useState<Finding | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [votes, setVotes] = useState({ count: 0, voted_by_me: false });
  const [comments, setComments] = useState<FindingComment[]>([]);
  const [draft, setDraft] = useState('');
  const [replyTo, setReplyTo] = useState<number | null>(null);
  const [posting, setPosting] = useState(false);

  const refreshSocial = useCallback((findingId: string) => {
    getFindingVotes(findingId).then(setVotes).catch(() => {});
    listFindingComments(findingId).then(setComments).catch(() => {});
  }, []);

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    getFinding(id)
      .then((data) => {
        setFinding(data);
        refreshSocial(id);
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setLoading(false));
  }, [id, refreshSocial]);

  async function handleVote() {
    if (!finding) return;
    try {
      const result = await toggleFindingVote(finding.id);
      setVotes({ count: result.count, voted_by_me: result.voted });
    } catch (err) {
      notify(err instanceof Error ? err.message : String(err), 'error');
    }
  }

  async function handleComment(event: React.FormEvent) {
    event.preventDefault();
    if (!finding || !draft.trim()) return;
    setPosting(true);
    try {
      await postFindingComment(finding.id, draft.trim(), replyTo ?? undefined);
      setDraft('');
      setReplyTo(null);
      refreshSocial(finding.id);
      notify('Comment posted.', 'success');
    } catch (err) {
      notify(err instanceof Error ? err.message : String(err), 'error');
    } finally {
      setPosting(false);
    }
  }

  if (loading) return <Skeleton lines={6} height="2rem" />;
  if (error) return <p className="error">{error}</p>;
  if (!finding) return <p>Finding not found.</p>;

  const topLevel = comments.filter((c) => c.parent_id === null);
  const repliesOf = (parentId: number) => comments.filter((c) => c.parent_id === parentId);
  const isOwner = user != null && user.id === finding.owner_id;

  return (
    <article className="finding">
      <header className="finding__head">
        <div className="finding__meta">
          {finding.accession && <code className="accession">{finding.accession}</code>}
          {finding.state === 'draft' && <span className="chip chip--draft">Draft</span>}
          {finding.doi && <span className="chip chip--verified">DOI-verified</span>}
        </div>

        <h1>{finding.title}</h1>

        <p className="finding__byline">
          {finding.owner_handle ? (
            <Link to={`/u/${finding.owner_handle}`}>
              {finding.owner_display_name ?? finding.owner_handle}
            </Link>
          ) : (
            (finding.owner_display_name ?? 'Unknown contributor')
          )}
          {finding.owner_orcid && (
            <>
              {' · '}
              <a
                href={`https://orcid.org/${finding.owner_orcid}`}
                target="_blank"
                rel="noreferrer noopener"
              >
                ORCID {finding.owner_orcid}
              </a>
            </>
          )}
          {finding.license_id && ` · ${finding.license_id}`}
        </p>

        {finding.doi && (
          <p className="finding__doi">
            Linked publication:{' '}
            <a
              href={`https://doi.org/${finding.doi}`}
              target="_blank"
              rel="noreferrer noopener"
            >
              {finding.doi}
            </a>
          </p>
        )}

        {finding.tags && finding.tags.length > 0 && (
          <div className="feed-card__tags">
            {finding.tags.map((tag) => (
              <Link key={tag} to={`/feed?tag=${encodeURIComponent(tag)}`} className="tag">
                {tag}
              </Link>
            ))}
          </div>
        )}

        {isOwner && (
          <Link to={`/findings/${finding.id}/edit`} className="ui-button">
            Edit this finding
          </Link>
        )}
      </header>

      {finding.abstract_md && <p className="finding__abstract">{finding.abstract_md}</p>}

      {finding.spectra.length > 0 && (
        <Card title={`Spectra in this finding (${finding.spectra.length})`}>
          <ul className="member-list">
            {finding.spectra.map((member) => (
              <li key={member.spectrum_id}>
                <Link to={`/spectra/${member.spectrum_id}`}>
                  {member.label ?? member.title ?? member.accession}
                </Link>
                {member.accession && <code className="accession">{member.accession}</code>}
                {member.state !== 'published' && (
                  <span className="chip chip--draft">{member.state}</span>
                )}
              </li>
            ))}
          </ul>
          <Link
            to={`/compare?ids=${finding.spectra.map((m) => m.spectrum_id).join(',')}`}
            className="ui-button ui-button--sm"
          >
            Compare all in the toolbox
          </Link>
        </Card>
      )}

      <section className="finding__thread">
        {finding.entries.map((entry) => (
          <FindingEntryView key={entry.id} entry={entry} members={finding.spectra} />
        ))}
      </section>

      <section className="finding__social">
        <div className="finding__actions">
          <Button onClick={handleVote} variant={votes.voted_by_me ? 'primary' : 'glass'}>
            ▲ {votes.count} {votes.voted_by_me ? 'Upvoted' : 'Upvote'}
          </Button>
          {!user && <span className="hint">Sign in to vote or comment.</span>}
        </div>

        <h3>Discussion ({comments.length})</h3>

        {topLevel.length === 0 && <p className="hint">No comments yet.</p>}

        <ul className="comments">
          {topLevel.map((comment) => (
            <li key={comment.id} className="comment">
              <div className="comment__head">
                {comment.author_handle ? (
                  <Link to={`/u/${comment.author_handle}`}>
                    {comment.author_display_name ?? comment.author_handle}
                  </Link>
                ) : (
                  <span>{comment.author_display_name ?? 'Someone'}</span>
                )}
                <time dateTime={comment.created_at}>
                  {new Date(comment.created_at).toLocaleDateString()}
                </time>
              </div>
              <p>{comment.body}</p>
              {user && (
                <button
                  type="button"
                  className="ui-button ui-button--ghost ui-button--sm"
                  onClick={() => setReplyTo(comment.id)}
                >
                  Reply
                </button>
              )}

              {repliesOf(comment.id).length > 0 && (
                <ul className="comments comments--replies">
                  {repliesOf(comment.id).map((reply) => (
                    <li key={reply.id} className="comment">
                      <div className="comment__head">
                        <span>{reply.author_display_name ?? reply.author_handle ?? 'Someone'}</span>
                        <time dateTime={reply.created_at}>
                          {new Date(reply.created_at).toLocaleDateString()}
                        </time>
                      </div>
                      <p>{reply.body}</p>
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>

        {user && (
          <form onSubmit={handleComment} className="comment-form">
            {replyTo !== null && (
              <p className="hint">
                Replying to comment #{replyTo}{' '}
                <button
                  type="button"
                  className="ui-button ui-button--ghost ui-button--sm"
                  onClick={() => setReplyTo(null)}
                >
                  Cancel
                </button>
              </p>
            )}
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="Add to the discussion…"
              rows={3}
              maxLength={2000}
            />
            <Button type="submit" variant="primary" loading={posting} disabled={!draft.trim()}>
              Post
            </Button>
          </form>
        )}
      </section>
    </article>
  );
}
