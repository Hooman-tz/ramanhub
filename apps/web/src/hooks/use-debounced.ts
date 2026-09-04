"use client";

import { useEffect, useState } from "react";

/**
 * The value, but only after it has stopped changing for `ms`.
 *
 * Every remote-backed input in the app wants this, and until now exactly one
 * had it — the handle-availability check on onboarding, with a private copy.
 * The library browse fired a request per keystroke against the whole
 * reference corpus for want of these six lines.
 *
 * Pick `ms` by what the user is doing with the result: around 200 ms for a
 * palette they are glancing at while typing, around 250 ms for a list they
 * stop and read.
 *
 * Moves to a shared package when apps/mobile lands in M5 and needs it too.
 */
export function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return debounced;
}
