import { useEffect, useState } from 'react';

type Theme = 'system' | 'light' | 'dark';

const STORAGE_KEY = 'ramanhub-theme';

/** Reads the stored preference synchronously so the first paint already has
 * the right theme. `index.html` applies the same attribute in an inline
 * script before React mounts, which is what prevents the white flash a
 * dark-mode user would otherwise see on every load. */
function storedTheme(): Theme {
  if (typeof localStorage === 'undefined') return 'system';
  const value = localStorage.getItem(STORAGE_KEY);
  return value === 'light' || value === 'dark' ? value : 'system';
}

/** Resolve 'system' to a concrete value and write it to `data-theme`.
 *
 * The CSS keys off that one attribute rather than also matching
 * `prefers-color-scheme`, so 'system' has to be resolved here — see the
 * comment above the dark block in tokens.css for why the tokens aren't
 * duplicated across both selectors. */
export function applyTheme(theme: Theme) {
  const resolved =
    theme === 'system'
      ? window.matchMedia?.('(prefers-color-scheme: dark)').matches
        ? 'dark'
        : 'light'
      : theme;
  document.documentElement.setAttribute('data-theme', resolved);
}

const OPTIONS: Array<{ value: Theme; label: string; icon: string }> = [
  { value: 'light', label: 'Light', icon: '☀' },
  { value: 'system', label: 'System', icon: '◐' },
  { value: 'dark', label: 'Dark', icon: '☾' },
];

/** An explicit three-way control rather than a two-state switch.
 *
 * `prefers-color-scheme` alone (what the app had) gives a user no way to
 * override their OS, and a plain light/dark toggle silently drops the
 * "follow my system" behaviour that most people actually want. Keeping
 * `system` as a real option is the difference. */
export default function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(storedTheme);

  useEffect(() => {
    applyTheme(theme);
    if (theme === 'system') {
      localStorage.removeItem(STORAGE_KEY);
    } else {
      localStorage.setItem(STORAGE_KEY, theme);
    }
  }, [theme]);

  // While following the system, track live OS changes. Without this the app
  // would keep whatever the OS was set to at page load and quietly stop
  // matching after a scheduled light/dark switch.
  useEffect(() => {
    if (theme !== 'system') return;
    const query = window.matchMedia?.('(prefers-color-scheme: dark)');
    if (!query) return;
    const onChange = () => applyTheme('system');
    query.addEventListener('change', onChange);
    return () => query.removeEventListener('change', onChange);
  }, [theme]);

  return (
    <div className="theme-toggle" role="group" aria-label="Color theme">
      {OPTIONS.map((option) => (
        <button
          key={option.value}
          type="button"
          className="theme-toggle__option"
          aria-pressed={theme === option.value}
          title={`${option.label} theme`}
          onClick={() => setTheme(option.value)}
        >
          <span aria-hidden="true">{option.icon}</span>
          <span className="sr-only">{option.label}</span>
        </button>
      ))}
    </div>
  );
}
