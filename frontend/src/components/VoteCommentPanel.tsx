import { useEffect, useState } from 'react';
import {
  getVotes,
  toggleVote,
  listComments,
  postComment,
  type VoteStatus,
  type Comment,
} from '../api/social';
import ShareButton from './ShareButton';

// Self-contained: takes only `spectrumId` and manages all its own state, so
// it can be dropped into SpectrumViewPage (or anywhere else) without
// depending on that page's local state. Deliberately not wired into
// SpectrumViewPage.tsx here — that integration happens separately.
export default function VoteCommentPanel({ spectrumId }: { spectrumId: string }) {
  const [voteStatus, setVoteStatus] = useState<VoteStatus | null>(null);
  const [voteLoading, setVoteLoading] = useState(true);
  const [voteError, setVoteError] = useState<string | null>(null);
  const [voting, setVoting] = useState(false);

  const [comments, setComments] = useState<Comment[]>([]);
  const [commentsLoading, setCommentsLoading] = useState(true);
  const [commentsError, setCommentsError] = useState<string | null>(null);

  const [newComment, setNewComment] = useState('');
  const [posting, setPosting] = useState(false);
  const [postError, setPostError] = useState<string | null>(null);

  useEffect(() => {
    refreshVotes();
    refreshComments();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [spectrumId]);

  function refreshVotes() {
    setVoteLoading(true);
    setVoteError(null);
    getVotes(spectrumId)
      .then(setVoteStatus)
      .catch((err) => setVoteError(err instanceof Error ? err.message : String(err)))
      .finally(() => setVoteLoading(false));
  }

  function refreshComments() {
    setCommentsLoading(true);
    setCommentsError(null);
    listComments(spectrumId)
      .then(setComments)
      .catch((err) => setCommentsError(err instanceof Error ? err.message : String(err)))
      .finally(() => setCommentsLoading(false));
  }

  async function handleToggleVote() {
    setVoting(true);
    setVoteError(null);
    try {
      const result = await toggleVote(spectrumId);
      setVoteStatus({ count: result.count, voted_by_me: result.voted });
    } catch (err) {
      setVoteError(err instanceof Error ? err.message : String(err));
    } finally {
      setVoting(false);
    }
  }

  async function handlePostComment(e: React.FormEvent) {
    e.preventDefault();
    const body = newComment.trim();
    if (!body) return;

    setPosting(true);
    setPostError(null);
    try {
      await postComment(spectrumId, body);
      setNewComment('');
      refreshComments();
    } catch (err) {
      setPostError(err instanceof Error ? err.message : String(err));
    } finally {
      setPosting(false);
    }
  }

  return (
    <div className="vote-comment-panel">
      <div className="vote-row">
        <button
          type="button"
          onClick={handleToggleVote}
          disabled={voting || voteLoading}
          aria-pressed={voteStatus?.voted_by_me ?? false}
        >
          {voteStatus?.voted_by_me ? '★ Upvoted' : '☆ Upvote'}
        </button>
        <span>{voteLoading ? '...' : (voteStatus?.count ?? 0)} vote(s)</span>
        {/* Beside the vote, because they are the two things you can do to
            someone else's spectrum — but distinct wording, since a share
            pushes this into other people's feeds and a vote does not. */}
        <ShareButton target={{ kind: 'spectrum', id: spectrumId }} />
      </div>
      {voteError && <p className="error">{voteError}</p>}

      <h3>Comments</h3>
      {commentsError && <p className="error">{commentsError}</p>}
      {commentsLoading && <p>Loading comments...</p>}
      {!commentsLoading && comments.length === 0 && <p>No comments yet.</p>}
      <ul>
        {comments.map((c) => (
          <li key={c.id}>
            <p>{c.body}</p>
            <small>{new Date(c.created_at).toLocaleString()}</small>
          </li>
        ))}
      </ul>

      <form onSubmit={handlePostComment}>
        <div className="field-row">
          <label htmlFor="new-comment">Add a comment</label>
          <textarea
            id="new-comment"
            rows={3}
            value={newComment}
            onChange={(e) => setNewComment(e.target.value)}
            maxLength={2000}
          />
        </div>
        <button type="submit" disabled={posting || !newComment.trim()}>
          {posting ? 'Posting...' : 'Post comment'}
        </button>
        {postError && <p className="error">{postError}</p>}
      </form>
    </div>
  );
}
