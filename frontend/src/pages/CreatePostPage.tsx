import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { createPost } from '../api/community';

export default function CreatePostPage() {
  const navigate = useNavigate();
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [kind, setKind] = useState<'announcement' | 'dataset'>('announcement');
  const [spectrumIds, setSpectrumIds] = useState('');
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const ids = spectrumIds.split(/[\s,]+/).map((id) => id.trim()).filter(Boolean);
    if (ids.length === 0) { setError('Add at least one published spectrum ID from your library.'); return; }
    try {
      const post = await createPost({ title, body, kind, spectrum_ids: ids });
      navigate(`/community/posts/${post.id}`);
    } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
  }
  return <section><p className="eyebrow">Public commons</p><h1>Share a research update</h1><p className="hint">Announcements may link only to your visible, published spectra.</p><form onSubmit={submit}>
    <div className="field-row"><label htmlFor="post-kind">Type</label><select id="post-kind" value={kind} onChange={(event) => setKind(event.target.value as typeof kind)}><option value="announcement">Research update</option><option value="dataset">Dataset announcement</option></select></div>
    <div className="field-row"><label htmlFor="post-title">Title</label><input id="post-title" value={title} onChange={(event) => setTitle(event.target.value)} required /></div>
    <div className="field-row"><label htmlFor="post-body">Update</label><textarea id="post-body" rows={6} value={body} onChange={(event) => setBody(event.target.value)} required /></div>
    <div className="field-row"><label htmlFor="post-spectra">Published spectrum IDs</label><textarea id="post-spectra" rows={3} value={spectrumIds} onChange={(event) => setSpectrumIds(event.target.value)} placeholder="Paste one or more IDs, separated by commas or new lines" required /></div>
    {error && <p className="error">{error}</p>}<button type="submit">Publish update</button>
  </form></section>;
}