import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { deleteCurrentUser, exportCurrentUser, getOrcidLinkUrl, updateCurrentUser } from '../api/client';
import { useAuth } from '../auth/useAuth';

export default function AccountPage() {
  const { user, loading } = useAuth();
  const navigate = useNavigate();
  const [displayName, setDisplayName] = useState(user?.display_name ?? '');
  const [handle, setHandle] = useState(user?.profile_handle ?? '');
  const [bio, setBio] = useState(user?.bio ?? '');
  const [affiliation, setAffiliation] = useState(user?.affiliation ?? '');
  const [isPublic, setIsPublic] = useState(user?.is_profile_public ?? false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!user) return;
    setDisplayName(user.display_name ?? '');
    setHandle(user.profile_handle ?? '');
    setBio(user.bio ?? '');
    setAffiliation(user.affiliation ?? '');
    setIsPublic(user.is_profile_public ?? false);
  }, [user]);

  if (loading) return <p>Loading account…</p>;
  if (!user || user.is_guest) return <p className="hint">Sign in with Google to manage a public researcher profile.</p>;

  async function save(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await updateCurrentUser({
        display_name: displayName || undefined,
        profile_handle: handle || undefined,
        bio: bio || undefined,
        affiliation: affiliation || undefined,
        is_profile_public: isPublic,
      });
      setMessage('Profile saved.');
    } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
  }
  async function downloadExport() {
    const data = await exportCurrentUser();
    const href = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }));
    const anchor = document.createElement('a'); anchor.href = href; anchor.download = 'spectra-insight-account-export.json'; anchor.click();
    URL.revokeObjectURL(href);
  }
  async function deleteAccount() {
    if (!window.confirm('Delete this account? Your published spectra remain visible but will be anonymized.')) return;
    await deleteCurrentUser();
    navigate('/login');
  }

  return (
    <section><p className="eyebrow">Account</p><h1>Researcher profile</h1>
      <p className="hint">Your email is private. A profile is visible only when you explicitly make it public.</p>
      <form onSubmit={save}>
        <div className="field-row"><label htmlFor="account-name">Display name</label><input id="account-name" value={displayName} onChange={(event) => setDisplayName(event.target.value)} /></div>
        <div className="field-row"><label htmlFor="account-handle">Public handle</label><input id="account-handle" value={handle} onChange={(event) => setHandle(event.target.value.toLowerCase())} placeholder="your-research-name" /></div>
        <div className="field-row"><label htmlFor="account-affiliation">Affiliation</label><input id="account-affiliation" value={affiliation} onChange={(event) => setAffiliation(event.target.value)} /></div>
        <div className="field-row"><label htmlFor="account-bio">Bio</label><textarea id="account-bio" rows={4} value={bio} onChange={(event) => setBio(event.target.value)} /></div>
        <label><input type="checkbox" checked={isPublic} onChange={(event) => setIsPublic(event.target.checked)} /> Make this researcher profile public</label>
        <div className="field-row"><button type="submit">Save profile</button></div>
        {message && <p className="hint">{message}</p>}{error && <p className="error">{error}</p>}
      </form>
      <h2>Researcher identity</h2>
      {user.orcid_verified_at && user.orcid_id ? (
        <p className="hint">Verified ORCID iD: <a href={`https://orcid.org/${user.orcid_id}`}>{user.orcid_id}</a></p>
      ) : (
        <p className="hint">Linking an ORCID iD verifies control of the record through ORCID. <a href={getOrcidLinkUrl()}>Link ORCID iD</a></p>
      )}
      <h2>Data portability</h2><p className="hint">Download a machine-readable copy of your profile and spectrum metadata. Raw data is not included in this export.</p>
      <button type="button" onClick={downloadExport}>Download account export</button>
      <h2>Delete account</h2><p className="hint">Deletion removes personal profile and community attribution. Published scientific records remain available as former-contributor records to preserve provenance.</p>
      <button type="button" className="danger-button" onClick={deleteAccount}>Delete account</button>
    </section>
  );
}