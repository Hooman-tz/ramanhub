import { Link } from 'react-router-dom';
import { useAuth } from '../auth/useAuth';
import { getGoogleLoginUrl } from '../api/client';
import { Skeleton } from '../components/ui';

export default function LoginPage() {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <div className="upload-hero">
        <Skeleton width="16rem" height="2rem" />
      </div>
    );
  }

  if (user) {
    return (
      <div className="upload-hero">
        <h1 className="upload-hero__title">You're signed in</h1>
        <p className="upload-hero__tagline">
          Signed in as <strong>{user.display_name ?? user.email}</strong>.
        </p>
        {/* Anchor styled as a button — a real <button> may not nest inside
            a link. */}
        <Link to="/upload" className="ui-button ui-button--primary">
          Go to upload
        </Link>
      </div>
    );
  }

  return (
    <div className="upload-hero">
      <p className="eyebrow">Spectra Insight workspace</p>
      <h1 className="upload-hero__title">Keep your research connected</h1>
      <p className="upload-hero__tagline">
        Sign in to keep a private library, build replayable processing pipelines, and publish when your data is ready.
      </p>
      {/* Full page navigation — this is a redirect-based OAuth flow, not a fetch. */}
      <a href={getGoogleLoginUrl()} className="ui-button ui-button--primary">
        Sign in with Google
      </a>
      <p className="upload-vendors">
        Google is the only sign-in method — no password to create or store.
      </p>
    </div>
  );
}
