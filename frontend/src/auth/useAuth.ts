import { useEffect, useState } from 'react';
import { getCurrentUser, type User } from '../api/client';

export interface UseAuthResult {
  user: User | null;
  loading: boolean;
  error: string | null;
}

/**
 * Calls GET /users/me on mount to determine whether the httpOnly session
 * cookie set by the OAuth redirect flow is valid. A 401/failure just means
 * "not logged in" (user stays null) rather than a fatal error.
 */
export function useAuth(): UseAuthResult {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    getCurrentUser()
      .then((u) => {
        if (!cancelled) setUser(u);
      })
      .catch((err) => {
        if (!cancelled) {
          setUser(null);
          // Not authenticated is an expected state, not necessarily an error
          // worth surfacing, but we keep it around for debugging.
          setError(err instanceof Error ? err.message : String(err));
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  return { user, loading, error };
}
