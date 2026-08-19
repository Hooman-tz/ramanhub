// "Report a bug" action (Module 5: Security, Logging & Operations).
//
// Opens a pre-filled GitHub "New Issue" form in a new tab, consistent with
// the "GitHub for spectral data" framing. Deliberately dependency-free (no
// backend call) -- it's a deep link, not a form submission.
//
// Renders nothing if VITE_GITHUB_REPO isn't set, since a private local
// worktree with no GitHub remote yet has nowhere for the link to go.
const GITHUB_REPO = import.meta.env.VITE_GITHUB_REPO;

// A short, human-shareable diagnostic id -- not a real backend session/error
// id (there's no Sentry event id to hand off yet; app/config.py's
// SENTRY_DSN is still unconfigured in local dev). Good enough to let a user
// reference "what I was looking at" when filing, and to grep for in
// structured server logs if the timestamp roughly lines up.
function diagnosticId(): string {
  return `web-${Date.now().toString(36)}`;
}

export default function ReportBugButton() {
  if (!GITHUB_REPO) return null;

  function handleClick() {
    const id = diagnosticId();
    const title = encodeURIComponent(`Bug report (${id})`);
    const body = encodeURIComponent(
      [
        '**What happened?**',
        '',
        '',
        '**Steps to reproduce**',
        '',
        '',
        '---',
        `Diagnostic id: \`${id}\``,
        `Page: ${window.location.href}`,
        `User agent: ${navigator.userAgent}`,
      ].join('\n'),
    );
    window.open(
      `https://github.com/${GITHUB_REPO}/issues/new?title=${title}&body=${body}`,
      '_blank',
      'noopener,noreferrer',
    );
  }

  return (
    <button type="button" onClick={handleClick} className="report-bug-button">
      Report a bug
    </button>
  );
}
