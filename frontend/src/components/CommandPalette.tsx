import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { searchSpectra, type SpectrumSearchResult } from '../api/search';

interface Command {
  id: string;
  label: string;
  hint?: string;
  run: () => void;
}

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const DEBOUNCE_MS = 200;

/** ⌘K / Ctrl-K command palette.
 *
 * Two things in one surface, which is the pattern worth copying from large
 * apps: it navigates, AND it searches the corpus. A user who knows a material
 * name shouldn't have to visit a search page first.
 *
 * Deliberately not a routing change — the palette overlays whatever you're
 * doing and returns you there on Escape, so it never costs you page state.
 *
 * Controlled rather than self-managed so the shell can also open it from the
 * visible sidebar button. A keyboard shortcut with no on-screen affordance is
 * a feature only its author knows about; the button is how anyone else ever
 * discovers the shortcut, which is why it advertises the keys. */
export default function CommandPalette({ open, onOpenChange }: Props) {
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SpectrumSearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  /** Where focus was when the palette opened, so Escape hands it back
   * instead of dumping the user at the top of the document. */
  const restoreFocusRef = useRef<HTMLElement | null>(null);

  const close = useCallback(() => {
    onOpenChange(false);
    setQuery('');
    setResults([]);
    setActive(0);
    restoreFocusRef.current?.focus?.();
  }, [onOpenChange]);

  const go = useCallback(
    (to: string) => {
      close();
      navigate(to);
    },
    [close, navigate],
  );

  const navigation = useMemo<Command[]>(
    () => [
      { id: 'upload', label: 'Upload spectra', hint: 'Toolbox', run: () => go('/upload') },
      { id: 'compare', label: 'Compare spectra', hint: 'Toolbox', run: () => go('/compare') },
      { id: 'routines', label: 'Routines', hint: 'Toolbox', run: () => go('/routines') },
      { id: 'library', label: 'My library', hint: 'Your data', run: () => go('/library') },
      { id: 'new-finding', label: 'Write a finding', hint: 'Create', run: () => go('/findings/new') },
      { id: 'feed', label: 'Feed', hint: 'Community', run: () => go('/feed') },
      { id: 'search', label: 'Search the commons', hint: 'Community', run: () => go('/search') },
      { id: 'trending', label: 'Trending', hint: 'Community', run: () => go('/trending') },
    ],
    [go],
  );

  // Open/close on the platform shortcut. Bound at the window so it works from
  // anywhere in the app, including while a page input has focus.
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        if (!open) restoreFocusRef.current = document.activeElement as HTMLElement | null;
        onOpenChange(!open);
      }
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onOpenChange]);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  // Debounced corpus search. Without the delay this fires a request per
  // keystroke, which is both wasteful and visibly janky as results reshuffle
  // mid-word. `stale` guards the out-of-order case: a slow early request must
  // not overwrite the results of a faster later one.
  useEffect(() => {
    const needle = query.trim();
    if (!open || needle.length < 2) {
      setResults([]);
      setSearching(false);
      return;
    }
    let stale = false;
    setSearching(true);
    const handle = setTimeout(() => {
      searchSpectra({ material_type: needle, limit: 5 })
        .then((rows) => {
          if (!stale) setResults(rows);
        })
        .catch(() => {
          if (!stale) setResults([]);
        })
        .finally(() => {
          if (!stale) setSearching(false);
        });
    }, DEBOUNCE_MS);
    return () => {
      stale = true;
      clearTimeout(handle);
    };
  }, [open, query]);

  const filteredNav = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return navigation;
    return navigation.filter((command) => command.label.toLowerCase().includes(needle));
  }, [navigation, query]);

  const commands = useMemo<Command[]>(
    () => [
      ...filteredNav,
      ...results.map((row) => ({
        id: row.id,
        label: row.title ?? row.material_type ?? 'Untitled spectrum',
        hint: row.accession ?? 'Spectrum',
        run: () => go(row.accession ? `/s/${row.accession}` : `/spectra/${row.id}`),
      })),
    ],
    [filteredNav, results, go],
  );

  // Clamp rather than reset: keeping the highlight near where it was is less
  // disorienting as results stream in than snapping to the top each time.
  useEffect(() => {
    setActive((current) => Math.min(current, Math.max(commands.length - 1, 0)));
  }, [commands.length]);

  if (!open) return null;

  function onKeyDown(event: React.KeyboardEvent) {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setActive((i) => (i + 1) % Math.max(commands.length, 1));
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setActive((i) => (i - 1 + commands.length) % Math.max(commands.length, 1));
    } else if (event.key === 'Enter') {
      event.preventDefault();
      commands[active]?.run();
    } else if (event.key === 'Escape') {
      event.preventDefault();
      close();
    }
  }

  return (
    <div className="palette-backdrop" onClick={close} role="presentation">
      <div
        className="palette"
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="palette__field">
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            aria-hidden="true"
            className="palette__icon"
          >
            <circle cx="10.5" cy="10.5" r="6.5" />
            <path d="m20 20-4.9-4.9" />
          </svg>
          <input
            ref={inputRef}
            className="palette__input"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Jump to a page, or search the commons by material…"
            aria-label="Command or search"
            aria-controls="palette-results"
            autoComplete="off"
            spellCheck={false}
          />
        </div>

        <ul className="palette__results" id="palette-results" role="listbox">
          {commands.length === 0 && (
            <li className="palette__empty">{searching ? 'Searching…' : 'No matches.'}</li>
          )}
          {commands.map((command, index) => (
            <li key={command.id}>
              <button
                type="button"
                role="option"
                aria-selected={index === active}
                className={index === active ? 'palette__item is-active' : 'palette__item'}
                onMouseEnter={() => setActive(index)}
                onClick={command.run}
              >
                <span className="palette__label">{command.label}</span>
                {command.hint && <span className="palette__hint">{command.hint}</span>}
              </button>
            </li>
          ))}
        </ul>

        <footer className="palette__footer">
          <span>
            <kbd>↑</kbd>
            <kbd>↓</kbd> move
          </span>
          <span>
            <kbd>↵</kbd> open
          </span>
          <span>
            <kbd>esc</kbd> close
          </span>
        </footer>
      </div>
    </div>
  );
}
