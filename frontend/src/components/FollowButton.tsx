import { useEffect, useState } from 'react';
import { getFollowState, toggleFollow } from '../api/client';
import { Button } from './ui';

interface Props {
  handle: string;
  /** Suppresses the button entirely on your own profile — you can't follow
   * yourself, and rendering a disabled control invites the question. */
  isSelf?: boolean;
  signedIn: boolean;
  onCountChange?: (followers: number) => void;
}

/** Follow / Following toggle.
 *
 * Fetches its own state on mount rather than taking it as a prop, so it can
 * paint in the right state on first render instead of flashing "Follow" at
 * someone who already follows this person. */
export default function FollowButton({ handle, isSelf, signedIn, onCountChange }: Props) {
  const [following, setFollowing] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getFollowState(handle)
      .then((state) => {
        if (cancelled) return;
        setFollowing(state.following);
        onCountChange?.(state.follower_count);
      })
      .catch(() => {
        if (!cancelled) setFollowing(false);
      });
    return () => {
      cancelled = true;
    };
    // onCountChange is intentionally excluded: callers pass an inline arrow
    // often enough that including it would refetch on every parent render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [handle]);

  if (isSelf) return null;

  async function onClick() {
    setBusy(true);
    setError(null);
    // Optimistic: the toggle is cheap and reversible, and waiting a round
    // trip to invert a button is the kind of latency people notice.
    const previous = following;
    setFollowing(!previous);
    try {
      const state = await toggleFollow(handle);
      setFollowing(state.following);
      onCountChange?.(state.follower_count);
    } catch (err) {
      setFollowing(previous);
      const message = err instanceof Error ? err.message : String(err);
      setError(
        message.includes('403')
          ? 'Sign in with Google to follow people.'
          : message.replace(/^API error \d+:\s*/, ''),
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <span className="follow-button">
      <Button
        variant={following ? 'ghost' : 'primary'}
        size="sm"
        onClick={onClick}
        loading={busy}
        disabled={!signedIn}
        title={signedIn ? undefined : 'Sign in to follow'}
      >
        {following ? 'Following' : 'Follow'}
      </Button>
      {error && <span className="error">{error}</span>}
    </span>
  );
}
