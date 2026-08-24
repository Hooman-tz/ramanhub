import type { ReactNode } from 'react';
import { Link, NavLink } from 'react-router-dom';
import { useAuth } from '../auth/useAuth';
import ReportBugButton from './ReportBugButton';
import ThemeToggle from './ThemeToggle';

/* Minimal 1.5px-stroke icons, inline so there's no icon-font/library
 * dependency. Sized by the shell CSS. */
const icons = {
  upload: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M12 16V4m0 0 4.5 4.5M12 4 7.5 8.5" />
      <path d="M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" />
    </svg>
  ),
  search: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true">
      <circle cx="10.5" cy="10.5" r="6.5" />
      <path d="m20 20-4.9-4.9" />
    </svg>
  ),
  library: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M5 4h4v16H5zM11 4h4v16h-4z" />
      <path d="m17 5 3.5 15" />
    </svg>
  ),
  trending: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="m3 16 6-6 4 4 8-8" />
      <path d="M15 6h6v6" />
    </svg>
  ),
  routines: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M12 3 3 8l9 5 9-5-9-5z" />
      <path d="m3 13 9 5 9-5" />
    </svg>
  ),
  feed: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M4 5h16v6H4zM4 15h10v4H4z" />
      <path d="M17 15h3v4h-3z" />
    </svg>
  ),
  compare: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M3 17c3-9 6 4 9-5s6 3 9-4" />
      <path d="M3 20h18" />
    </svg>
  ),
  login: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true">
      <circle cx="12" cy="8.5" r="4" />
      <path d="M4.5 20a7.5 7.5 0 0 1 15 0" />
    </svg>
  ),
};

/* Grouped so the sidebar reads as three jobs rather than one flat list:
   the toolbox you work in, your own data, and the shared commons. */
const NAV_GROUPS: Array<{ label: string; items: Array<{ to: string; label: string; icon: JSX.Element }> }> = [
  {
    label: 'Toolbox',
    items: [
      { to: '/upload', label: 'Upload', icon: icons.upload },
      { to: '/compare', label: 'Compare', icon: icons.compare },
      { to: '/routines', label: 'Routines', icon: icons.routines },
    ],
  },
  {
    label: 'Your data',
    items: [{ to: '/library', label: 'Library', icon: icons.library }],
  },
  {
    label: 'Community',
    items: [
      { to: '/feed', label: 'Feed', icon: icons.feed },
      { to: '/search', label: 'Search', icon: icons.search },
      { to: '/trending', label: 'Trending', icon: icons.trending },
    ],
  },
];

function initials(name: string): string {
  return name
    .split(/\s+/)
    .map((part) => part[0])
    .filter(Boolean)
    .slice(0, 2)
    .join('')
    .toUpperCase();
}

export default function AppShell({ children }: { children: ReactNode }) {
  const { user } = useAuth();

  return (
    <div className="shell">
      <aside className="shell__sidebar">
        <Link to="/" className="shell__brand">
          <img src="/favicon.svg" alt="" className="shell__brand-mark" />
          RamanHub
        </Link>

        <nav className="shell__nav" aria-label="Primary">
          {NAV_GROUPS.map((group) => (
            <div key={group.label} className="shell__nav-group">
              <p className="shell__nav-label">{group.label}</p>
              {group.items.map((item) => (
                <NavLink key={item.to} to={item.to} className="shell__nav-link">
                  {item.icon}
                  {item.label}
                </NavLink>
              ))}
            </div>
          ))}
          {(!user || user.is_guest) && (
            <NavLink to="/login" className="shell__nav-link">
              {icons.login}
              Sign in
            </NavLink>
          )}
        </nav>

        <div className="shell__footer">
          <ThemeToggle />
          {user && (
            <div className="shell__user" title={user.is_guest ? 'Guest session' : user.email}>
              {user.avatar_url ? (
                <img src={user.avatar_url} alt="" className="shell__user-avatar" />
              ) : (
                <span className="shell__user-avatar">
                  {user.is_guest ? 'G' : initials(user.name ?? user.email)}
                </span>
              )}
              <span className="shell__user-name">
                {user.is_guest ? (
                  'Guest session'
                ) : user.handle ? (
                  <Link to={`/u/${user.handle}`}>{user.name ?? user.display_name ?? user.email}</Link>
                ) : (
                  (user.name ?? user.email)
                )}
              </span>
            </div>
          )}
          <ReportBugButton />
          <nav className="shell__legal" aria-label="Legal">
            <Link to="/terms">Terms</Link> · <Link to="/privacy">Privacy</Link>
          </nav>
        </div>
      </aside>

      <main className="shell__main">{children}</main>
    </div>
  );
}
