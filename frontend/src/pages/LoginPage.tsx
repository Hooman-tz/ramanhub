import { Link } from 'react-router-dom';
import { useAuth } from '../auth/useAuth';
import { getGoogleLoginUrl } from '../api/client';

export default function LoginPage() {
  const { user, loading } = useAuth();

  if (loading) {
    return <p>Checking session...</p>;
  }

  if (user) {
    return (
      <div>
        <p>
          Already signed in as <strong>{user.name ?? user.email}</strong>.
        </p>
        <Link to="/upload">Go to upload</Link>
      </div>
    );
  }

  return (
    <div>
      <h1>RamanHub</h1>
      <p>Sign in to upload and manage spectral data.</p>
      {/* Full page navigation — this is a redirect-based OAuth flow, not a fetch. */}
      <a href={getGoogleLoginUrl()}>
        <button type="button">Sign in with Google</button>
      </a>
    </div>
  );
}
