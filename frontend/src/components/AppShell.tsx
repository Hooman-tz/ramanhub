import type { ReactNode } from 'react';
import { Link, NavLink } from 'react-router-dom';
import { useAuth } from '../auth/useAuth';
import ReportBugButton from './ReportBugButton';

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
  login: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true">
      <circle cx="12" cy="8.5" r="4" />
      <path d="M4.5 20a7.5 7.5 0 0 1 15 0" />
    </svg>
  ),
};

const NAV_ITEMS = [
  { to: '/upload', label: 'Upload', icon: icons.upload },
  { to: '/library', label: 'Library', icon: icons.library },
  { to: '/search', label: 'Search', icon: icons.search },
  { to: '/routines', label: 'Processing', icon: icons.routines },
  { to: '/analysis', label: 'Explore', icon: icons.search },
  { to: '/commons', label: 'Commons', icon: icons.trending },
  { to: '/trending', label: 'Trending', icon: icons.trending },
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
          <span>Spectra<span className="shell__brand-accent">Insight</span></span>
        </Link>
        <p className="shell__workspace-label">Private workspace</p>

        <nav className="shell__nav" aria-label="Primary">
          {NAV_ITEMS.map((item) => (
            <NavLink key={item.to} to={item.to} className="shell__nav-link">
              {item.icon}
              {item.label}
            </NavLink>
          ))}
          {(!user || user.is_guest) && (
            <NavLink to="/login" className="shell__nav-link">
              {icons.login}
              Sign in
            </NavLink>
          )}
          {user && !user.is_guest && (
            <>
              <NavLink to="/notifications" className="shell__nav-link">
                {icons.trending}
                Notifications
              </NavLink>
              <NavLink to="/account" className="shell__nav-link">
                {icons.login}
                Account
              </NavLink>
            </>
          )}
        </nav>

        <div className="shell__footer">
          {user && (
            <div className="shell__user" title={user.is_guest ? 'Guest session' : user.email}>
              {user.avatar_url ? (
                <img src={user.avatar_url} alt="" className="shell__user-avatar" />
              ) : (
                <span className="shell__user-avatar">
                  {user.is_guest ? 'G' : initials(user.display_name ?? user.email)}
                </span>
              )}
              <span className="shell__user-name">
                {user.is_guest ? 'Guest session' : (user.display_name ?? user.email)}
              </span>
            </div>
          )}
          <ReportBugButton />
          <Link to="/upload" className="shell__footer-link">Start a new analysis <span aria-hidden="true">↗</span></Link>
          <nav className="shell__legal" aria-label="Legal">
            <Link to="/terms">Terms</Link> · <Link to="/privacy">Privacy</Link>
          </nav>
        </div>
      </aside>

      <main className="shell__main">{children}</main>
    </div>
  );
}
