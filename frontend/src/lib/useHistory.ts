import { useCallback, useMemo, useRef, useState } from 'react';

interface HistoryState<T> {
  past: T[];
  present: T;
  future: T[];
}

export interface History<T> {
  state: T;
  set: (next: T, coalesceKey?: string) => void;
  /** Replace the value AND discard the history. For adopting a new
   * server-side truth — undoing across a save would restore edits the server
   * no longer knows about. */
  reset: (next: T) => void;
  undo: () => void;
  redo: () => void;
  canUndo: boolean;
  canRedo: boolean;
}

/** Undo/redo over a single value.
 *
 * `coalesceKey` is the part worth explaining. A parameter field fires an
 * onChange per keystroke, so a naive stack records "0", "0.", "0.0", "0.05"
 * as four separate undo entries and Ctrl-Z becomes a character-at-a-time
 * backspace — undo that nobody can use. Passing a key (say
 * `param:2:min_cm1`) makes consecutive edits sharing that key REPLACE the
 * top of the stack instead of pushing onto it, so one undo reverts the whole
 * field edit. Changing field, or making any structural change, breaks the
 * run and starts a fresh entry.
 *
 * Deliberately not capped: pipelines are a handful of steps, and the arrays
 * held here are small enough that a bounded ring buffer would be complexity
 * bought for nothing. */
export function useHistory<T>(initial: T): History<T> {
  const [history, setHistory] = useState<HistoryState<T>>({
    past: [],
    present: initial,
    future: [],
  });
  const lastKey = useRef<string | null>(null);

  const set = useCallback((next: T, coalesceKey?: string) => {
    setHistory((current) => {
      const coalesce = coalesceKey != null && coalesceKey === lastKey.current;
      lastKey.current = coalesceKey ?? null;
      return {
        // On a coalesced edit the previous present is dropped rather than
        // pushed: the entry already on the stack is the pre-edit value, which
        // is the one undo should restore.
        past: coalesce ? current.past : [...current.past, current.present],
        present: next,
        future: [],
      };
    });
  }, []);

  const reset = useCallback((next: T) => {
    lastKey.current = null;
    setHistory({ past: [], present: next, future: [] });
  }, []);

  const undo = useCallback(() => {
    lastKey.current = null;
    setHistory((current) => {
      if (current.past.length === 0) return current;
      const previous = current.past[current.past.length - 1];
      return {
        past: current.past.slice(0, -1),
        present: previous,
        future: [current.present, ...current.future],
      };
    });
  }, []);

  const redo = useCallback(() => {
    lastKey.current = null;
    setHistory((current) => {
      if (current.future.length === 0) return current;
      const [next, ...rest] = current.future;
      return {
        past: [...current.past, current.present],
        present: next,
        future: rest,
      };
    });
  }, []);

  return useMemo(
    () => ({
      state: history.present,
      set,
      reset,
      undo,
      redo,
      canUndo: history.past.length > 0,
      canRedo: history.future.length > 0,
    }),
    [history, set, reset, undo, redo],
  );
}
