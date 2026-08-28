import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { getPublicProfile, type PublicProfile } from '../api/community';

export default function PublicProfilePage() {
  const { handle = '' } = useParams();
  const [profile, setProfile] = useState<PublicProfile | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getPublicProfile(handle).then(setProfile).catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, [handle]);
  if (error) return <p className="error">{error}</p>;
  if (!profile) return <p>Loading public profile…</p>;

  return (
    <section>
      <p className="eyebrow">Researcher profile</p>
      <h1>{profile.display_name}</h1>
      {profile.affiliation && <p>{profile.affiliation}</p>}
      {profile.orcid_id && <p><a href={`https://orcid.org/${profile.orcid_id}`}>ORCID {profile.orcid_id}</a></p>}
      {profile.bio && <p>{profile.bio}</p>}
      {profile.research_interests.length > 0 && <p className="hint">Research interests: {profile.research_interests.join(' · ')}</p>}
      <h2>Published spectra</h2>
      {profile.spectra.length === 0 ? <p className="hint">No visible public spectra.</p> : (
        <ul>
          {profile.spectra.map((spectrum) => <li key={spectrum.id}><Link to={`/public/spectra/${spectrum.id}`}>{spectrum.title ?? spectrum.id}</Link> · {spectrum.modality}</li>)}
        </ul>
      )}
    </section>
  );
}