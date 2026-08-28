import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { listPosts, type CommunityPost } from '../api/community';
import { useAuth } from '../auth/useAuth';

export default function CommonsPage() {
  const { user } = useAuth();
  const [posts, setPosts] = useState<CommunityPost[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listPosts().then(setPosts).catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, []);

  return (
    <section>
      <div className="page-heading">
        <div>
          <p className="eyebrow">Public scientific commons</p>
          <h1>Research updates and reusable spectra</h1>
          <p className="hint">Community activity is separate from objective spectrum search and never changes scientific ranking.</p>
        </div>
        {user && !user.is_guest ? <Link className="button" to="/community/new">Share an update</Link> : <Link className="button" to="/login">Sign in to contribute</Link>}
      </div>
      {error && <p className="error">{error}</p>}
      {!error && posts.length === 0 && <p className="hint">No public research updates yet. Published spectra remain discoverable through Search.</p>}
      <div className="stack">
        {posts.map((post) => (
          <article className="card" key={post.id}>
            <p className="eyebrow">{post.kind === 'dataset' ? 'Dataset announcement' : 'Research update'}</p>
            <h2><Link to={`/community/posts/${post.id}`}>{post.title}</Link></h2>
            <p>{post.body}</p>
            <p className="hint">
              {post.author.profile_path ? <Link to={post.author.profile_path}>{post.author.display_name}</Link> : post.author.display_name}
              {' · '}{post.spectra.length} linked spectrum{post.spectra.length === 1 ? '' : 'a'} · {post.reaction_count} reaction{post.reaction_count === 1 ? '' : 's'}
            </p>
          </article>
        ))}
      </div>
    </section>
  );
}