# Public commons API contracts

## Public boundaries

- `GET /public/spectra/{id}` is the canonical API record for a visible public
  spectrum. It exposes confirmed metadata, license, DOI/publication evidence,
  reproducibility provenance, citation/download paths, and a safe contributor
  summary. It never exposes the contributor’s email, storage paths, uploaded
  filename, session information, or raw user ID.
- `GET /public/spectra/{id}/citation` returns plain-text or BibTeX citation
  text. `GET /public/spectra/{id}/share-preview` returns safe title,
  description, author, and canonical path data for share UI.
- `GET /s/{id}` is a validated short redirect. It first checks public
  visibility and only redirects to the configured frontend/public domain; it
  never accepts an arbitrary destination URL.
- `GET /profiles/{handle}` returns only public-profile fields and that
  contributor’s visible published spectra. A profile is unavailable until the
  contributor opts in.

## Community contracts

- `GET /community/posts` and `GET /community/posts/{id}` list visible research
  updates and dataset announcements. Posts must link to at least one visible,
  published spectrum owned by their author.
- Full accounts use `POST /community/posts`, `PATCH/DELETE
  /community/posts/{id}`, `POST /community/posts/{id}/reactions`, and the
  post-comment routes. Guests may browse but cannot perform identity-carrying
  actions.
- `POST /community/reports` accepts reports for public spectra, profiles,
  posts, or comments. Duplicate reports from one person about the same target
  return a conflict rather than creating unbounded copies.
- Moderator-only report resolution is available under `/community/moderation`.
  Hiding content removes it from visitor endpoints without changing the
  scientific-search ordering model.
- `/community/notifications` and `/community/notification-preferences`
  provide opt-out in-app delivery for comments, reactions, and moderation
  outcomes.

## Identity and account lifecycle

- `GET/PATCH /users/me` is private. It contains email and profile-editing
  fields and must never be used as a public author response.
- `GET /users/me/export` provides a portable JSON account export with profile
  and spectrum metadata, not raw file bytes or storage locations.
- `DELETE /users/me` anonymizes the account and hides profile/community
  content while preserving published records as “Former contributor” evidence.
- ORCID uses `/users/me/orcid/link` and `/users/me/orcid/callback` as a
  proof-of-control link for an existing account. It is not a sign-in method,
  and ORCID access tokens are never persisted.

## Ranking invariant

`/search/spectra` remains objective and ordered by publication time. Votes,
comments, post reactions, reports, and notifications are never joined into
scientific search ranking. Vote activity belongs exclusively to `/trending`.