import { useEffect, useState } from 'react';
import { getShareState, toggleShare } from '../api/client';

interface Props {
  target: { kind: 'spectrum' | 'finding'; id: string };
}

/** Share / Shared toggle.
 *
 * A share is a different act from a vote and the wording says so: a vote is
 * "this is good", a share is "my followers should see this". That difference
 * is why it carries more weight in feed ranking than a vote does — putting
 * something in front of your own followers costs you a little if it turns out
 * to be bad, which makes it the more expensive signal to fake. */
export default function ShareButton({ target }: Props) {
  const [count, setCount] = useState(0);
  const [shared, setShared] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getShareState(target)
      .then((state) => {
        if (cancelled) return;
        setCount(state.count);
        setShared(state.shared_by_me);
      })
      .catch(() => undefined)
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [target.kind, target.id]);

  async function onClick() {
    setBusy(true);
    setError(null);
    try {
      const state = await toggleShare(target);
      setShared(state.shared);
      setCount(state.count);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setError(
        message.includes('403')
          ? 'Sign in with Google to share.'
          : message.replace(/^API error \d+:\s*/, ''),
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <span className="share-row">
      <button type="button" onClick={onClick} disabled={busy || loading} aria-pressed={shared}>
        {shared ? '↺ Shared' : '↗ Share'}
      </button>
      <span>{loading ? '…' : count} share{count === 1 ? '' : 's'}</span>
      {error && <span className="error">{error}</span>}
    </span>
  );
}
