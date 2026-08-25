import { describe, expect, it } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { useHistory } from './useHistory';

describe('useHistory', () => {
  it('starts with nothing to undo or redo', () => {
    const { result } = renderHook(() => useHistory('a'));
    expect(result.current.state).toBe('a');
    expect(result.current.canUndo).toBe(false);
    expect(result.current.canRedo).toBe(false);
  });

  it('undoes and redoes a single change', () => {
    const { result } = renderHook(() => useHistory('a'));

    act(() => result.current.set('b'));
    expect(result.current.state).toBe('b');
    expect(result.current.canUndo).toBe(true);

    act(() => result.current.undo());
    expect(result.current.state).toBe('a');
    expect(result.current.canRedo).toBe(true);

    act(() => result.current.redo());
    expect(result.current.state).toBe('b');
  });

  it('walks back through several changes in order', () => {
    const { result } = renderHook(() => useHistory(0));
    act(() => result.current.set(1));
    act(() => result.current.set(2));
    act(() => result.current.set(3));

    act(() => result.current.undo());
    expect(result.current.state).toBe(2);
    act(() => result.current.undo());
    expect(result.current.state).toBe(1);
    act(() => result.current.undo());
    expect(result.current.state).toBe(0);
    expect(result.current.canUndo).toBe(false);
  });

  it('drops the redo stack once a new change is made', () => {
    const { result } = renderHook(() => useHistory('a'));
    act(() => result.current.set('b'));
    act(() => result.current.undo());
    expect(result.current.canRedo).toBe(true);

    act(() => result.current.set('c'));
    expect(result.current.canRedo).toBe(false);
    act(() => result.current.undo());
    expect(result.current.state).toBe('a');
  });

  it('coalesces consecutive edits sharing a key into one undo entry', () => {
    // The reason the key exists: a param field fires onChange per keystroke,
    // and without coalescing Ctrl-Z becomes a character-at-a-time backspace.
    const { result } = renderHook(() => useHistory(''));
    act(() => result.current.set('0', 'param:min'));
    act(() => result.current.set('0.', 'param:min'));
    act(() => result.current.set('0.0', 'param:min'));
    act(() => result.current.set('0.05', 'param:min'));

    expect(result.current.state).toBe('0.05');
    act(() => result.current.undo());
    expect(result.current.state).toBe('');
    expect(result.current.canUndo).toBe(false);
  });

  it('starts a fresh entry when the coalesce key changes', () => {
    const { result } = renderHook(() => useHistory('start'));
    act(() => result.current.set('a1', 'field:a'));
    act(() => result.current.set('a2', 'field:a'));
    act(() => result.current.set('b1', 'field:b'));

    act(() => result.current.undo());
    expect(result.current.state).toBe('a2');
    act(() => result.current.undo());
    expect(result.current.state).toBe('start');
  });

  it('does not coalesce an unkeyed change into a keyed run', () => {
    const { result } = renderHook(() => useHistory('start'));
    act(() => result.current.set('a1', 'field:a'));
    act(() => result.current.set('structural'));

    act(() => result.current.undo());
    expect(result.current.state).toBe('a1');
  });

  it('reset discards the history so undo cannot cross a save', () => {
    // Undoing past a save would restore edits the server no longer knows
    // about, leaving the UI and the server disagreeing about the truth.
    const { result } = renderHook(() => useHistory('a'));
    act(() => result.current.set('b'));
    act(() => result.current.reset('saved'));

    expect(result.current.state).toBe('saved');
    expect(result.current.canUndo).toBe(false);
    expect(result.current.canRedo).toBe(false);
  });

  it('undo and redo are no-ops at the ends of the stack', () => {
    const { result } = renderHook(() => useHistory('only'));
    act(() => result.current.undo());
    expect(result.current.state).toBe('only');
    act(() => result.current.redo());
    expect(result.current.state).toBe('only');
  });
});
