import { apiRequest } from './client';

export interface PublicAuthor {
  display_name: string;
  avatar_url: string | null;
  orcid_id: string | null;
  profile_path: string | null;
}

export interface PublicSpectrumRecord {
  id: string;
  title: string | null;
  description: string | null;
  modality: string;
  metadata: Record<string, unknown> | null;
  quality_flags: Record<string, unknown> | null;
  published_at: string | null;
  author: PublicAuthor;
  license: { id: string; name: string; url: string } | null;
  provenance: Record<string, unknown>;
  publication: { doi: string; snapshot: Record<string, unknown> } | null;
  canonical_path: string;
  canonical_url: string | null;
  citation_url: string;
  download_url: string;
}

export interface PublicProfile {
  id: string;
  handle: string;
  display_name: string;
  avatar_url: string | null;
  orcid_id: string | null;
  affiliation: string | null;
  bio: string | null;
  research_interests: string[];
  joined_at: string;
  spectra: Array<{ id: string; title: string | null; modality: string; doi: string | null }>;
}

export interface CommunityPost {
  id: string;
  kind: 'announcement' | 'dataset';
  title: string;
  body: string;
  author: PublicAuthor;
  publication_id: string | null;
  spectrum_ids: string[];
  spectra: Array<{ id: string; title: string | null; modality: string }>;
  reaction_count: number;
  reacted_by_me: boolean;
  comment_count: number;
  created_at: string;
  canonical_path: string;
}

export interface CommunityComment {
  id: number;
  body: string;
  created_at: string;
  author: PublicAuthor;
}

export interface CommunityNotification {
  id: string;
  kind: string;
  payload: Record<string, unknown>;
  read_at: string | null;
  created_at: string;
}

export function listPosts(): Promise<CommunityPost[]> {
  return apiRequest<CommunityPost[]>('/community/posts');
}

export function getPost(id: string): Promise<CommunityPost> {
  return apiRequest<CommunityPost>(`/community/posts/${id}`);
}

export function createPost(payload: {
  title: string;
  body: string;
  kind: 'announcement' | 'dataset';
  spectrum_ids: string[];
  publication_id?: string;
}): Promise<CommunityPost> {
  return apiRequest<CommunityPost>('/community/posts', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function togglePostReaction(id: string): Promise<{ reacted: boolean; count: number }> {
  return apiRequest(`/community/posts/${id}/reactions`, { method: 'POST' });
}

export function listPostComments(id: string): Promise<CommunityComment[]> {
  return apiRequest<CommunityComment[]>(`/community/posts/${id}/comments`);
}

export function postPostComment(id: string, body: string): Promise<CommunityComment> {
  return apiRequest<CommunityComment>(`/community/posts/${id}/comments`, {
    method: 'POST',
    body: JSON.stringify({ body }),
  });
}

export function getPublicSpectrum(id: string): Promise<PublicSpectrumRecord> {
  return apiRequest<PublicSpectrumRecord>(`/public/spectra/${id}`);
}

export function getPublicProfile(handle: string): Promise<PublicProfile> {
  return apiRequest<PublicProfile>(`/profiles/${handle}`);
}

export function listNotifications(): Promise<CommunityNotification[]> {
  return apiRequest<CommunityNotification[]>('/community/notifications');
}

export function markNotificationRead(id: string): Promise<{ id: string; read_at: string }> {
  return apiRequest(`/community/notifications/${id}/read`, { method: 'POST' });
}