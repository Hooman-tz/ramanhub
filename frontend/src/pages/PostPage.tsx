import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { getPost, listPostComments, postPostComment, togglePostReaction, type CommunityComment, type CommunityPost } from '../api/community';
import { useAuth } from '../auth/useAuth';

export default function PostPage() {
  const { id = '' } = useParams();
  const { user } = useAuth();
  const [post, setPost] = useState<CommunityPost | null>(null);
  const [comments, setComments] = useState<CommunityComment[]>([]);
  const [body, setBody] = useState('');
  const [error, setError] = useState<string | null>(null);

  function refresh() {
    Promise.all([getPost(id), listPostComments(id)]).then(([nextPost, nextComments]) => {
      setPost(nextPost);
      setComments(nextComments);
    }).catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }
  useEffect(refresh, [id]);

  async function react() {
    try { await togglePostReaction(id); refresh(); } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
  }
  async function comment(event: React.FormEvent) {
    event.preventDefault();
    if (!body.trim()) return;
    try { await postPostComment(id, body.trim()); setBody(''); refresh(); } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
  }

  if (error) return <p className="error">{error}</p>;
  if (!post) return <p>Loading community post…</p>;
  const canInteract = Boolean(user && !user.is_guest);
  return (
    <section>
      <p className="eyebrow">{post.kind === 'dataset' ? 'Dataset announcement' : 'Research update'}</p>
      <h1>{post.title}</h1>
      <p>{post.body}</p>
      <p className="hint">{post.author.profile_path ? <Link to={post.author.profile_path}>{post.author.display_name}</Link> : post.author.display_name}</p>
      <h2>Linked spectra</h2>
      <ul>{post.spectra.map((spectrum) => <li key={spectrum.id}><Link to={`/public/spectra/${spectrum.id}`}>{spectrum.title ?? spectrum.id}</Link></li>)}</ul>
      {canInteract ? <button type="button" onClick={react}>{post.reacted_by_me ? 'Remove reaction' : 'React'} ({post.reaction_count})</button> : <p className="hint"><Link to="/login">Sign in</Link> to react or comment.</p>}
      <h2>Discussion</h2>
      {comments.map((commentItem) => <article className="card" key={commentItem.id}><p>{commentItem.body}</p><small>{commentItem.author.display_name} · {new Date(commentItem.created_at).toLocaleString()}</small></article>)}
      {canInteract && <form onSubmit={comment}><div className="field-row"><label htmlFor="post-comment">Add a comment</label><textarea id="post-comment" rows={3} value={body} onChange={(event) => setBody(event.target.value)} /></div><button type="submit">Post comment</button></form>}
    </section>
  );
}