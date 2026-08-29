# RamanHub: two parallel tracks, compared

**Generated 2026-08-28.** Both tracks are now committed. Nothing in this
document required a checkout; every figure comes from `git` operations
between refs, and the working tree was never modified.

| | Track A | Track B |
| --- | --- | --- |
| Branch | `feature/mvp-toolbox-social` | `replit/aug26-snapshot` |
| Tip | `db6c37b` | `8644880` |
| Dated | 2026-08-25 | 2026-08-26 |
| Origin | this Claude Code session | Replit (`replit.md`) |
| vs `main` (`4171fe1`) | 143 files, +19,926 / −772 | 195 files, +20,660 / −2,190 |
| Was it committed? | yes | no — snapshotted on 2026-08-28 |

They are **siblings, not successive versions**: both fork from `main`.
The two are close to the same size. Track B was previously undercounted
because ~17,000 of its lines were in untracked files.

---

## 1. The headline: these are different *layers*, not rival implementations

Track A builds the **social / citation layer**. Track B builds the
**data-integrity and analysis layer**. They barely attempt the same job.

### Only in Track A

| Kind | Items |
| --- | --- |
| Routers | `export.py`, `feed.py`, `findings.py`, `follows.py`, `pins.py`, `shares.py` |
| Models | `accession.py`, `curation.py`, `finding.py`, `graph.py`, `handles.py` |
| Pages | `ComparePage`, `FeedPage`, `FindingComposerPage`, `FindingPage`, `ProfilePage`, `SettingsPage` |
| Other | `thumbnails.py`, `profile_stats.py`, `activity.py`, `ranking.py`, `llm_providers.py`, `export/` |

Themes: findings as citable threads, accession IDs, follow graph, shares,
pins, collections, profile stats, contribution chart, SVG spectrum
thumbnails, ZIP/citation export, **and the entire OpenRouter parser**.

### Only in Track B

| Kind | Items |
| --- | --- |
| Routers | `community.py`, `orcid.py`, `profiles.py`, `public_records.py` |
| Models | `analysis.py`, `publication.py`, `similarity.py` |
| Pages | `AccountPage`, `AnalysisPage`, `CommonsPage`, `CreatePostPage`, `NotificationsPage`, `PostPage`, `PublicProfilePage`, `PublicRecordPage` |
| Other | `analysis/engine.py`, `analysis/worker.py`, `ingestion/worker.py`, `auth/orcid_oauth.py`, `discovery/`, `raman_contract.py`, `spectrum_lifecycle.py` |

Themes: real ORCID OAuth, a public commons with posts and notifications,
an async analysis engine + worker, similarity/discovery, publication
snapshots, and hardened ingestion (leases, heartbeats, retry accounting,
canonicalization versioning, dedupe hashes, quality flags).

**Correction to an earlier claim of mine:** `licenses.py`, `routines.py`,
`trending.py`, `processing.py` and `doi.py` are inherited from `main` and
belong to *both* tracks. I previously attributed them to Track B.

---

## 2. The database layer merges for free

This is the best news in the document, and it is the part that usually
kills a merge like this.

**Two Alembic heads**, forking at `e41f7a90c2d1_add_users_is_guest`:

| Track | Chain | Head |
| --- | --- | --- |
| A | `a1f2c3d4e5b6` → `b2c3d4e5f6a7` → `1e817525ab60` | `1e817525ab60` |
| B | `c61d7f4a2b9e` → `d83a6b1e5c7f` → `f1a9c2e6b4d8` → `a4e7d2b8c6f1` → `c8f2a1d7e4b6` | `c8f2a1d7e4b6` |

Tables created after the fork:

- **A:** `findings`, `finding_entries`, `finding_spectra`, `follows`,
  `shares`, `pins`, `collections`, `collection_spectra`, `handle_history`
- **B:** `analysis_runs`, `analysis_datasets`, `analysis_dataset_spectra`,
  `similarity_features`, `publication_snapshots`

**Table-name collisions: none. Column-name collisions: none.**

The only table both chains touch is `spectra`, and even there the added
columns are disjoint — A adds `accession`; B adds
`canonicalization_version`, `parent_spectrum_id`, `quality_flags`.

Resolution is therefore a mechanical two-parent merge revision:

```bash
alembic merge -m "merge track A and track B" 1e817525ab60 c8f2a1d7e4b6
```

No data migration, no rename, no reconciliation of competing schemas.

---

## 3. Code conflicts: 30 files, and they cluster

Of the 44 files both tracks modify, a real in-memory three-way merge
(`git merge-tree`) auto-resolves 14 and **conflicts on 30**. Sized by lines
each track changed relative to `main`:

### Tier 1 — genuinely contested, needs a human decision

| File | A | B | Why |
| --- | ---: | ---: | --- |
| `backend/app/ingestion/jobs.py` | 65 | 348 | **The important one.** A's header-trim (5,690 → 45 tokens) lands in the same file B rewrote for leases and provenance. |
| `backend/app/routers/analysis.py` | 276 | 280 | Both rewrote it — A synchronously, B against a worker queue. |
| `backend/app/models/social.py` | 147 | 150 | A retargets votes/comments to findings and adds `Share`; B extends for the commons. |
| `backend/app/routers/search.py` | 101 | 118 | A adds engagement ranking; B adds discovery/similarity. |
| `backend/app/routers/users.py` | 93 | 108 | A adds handles/bio/affiliation; B adds ORCID OAuth linking. |
| `frontend/src/api/client.ts` | 190 | 130 | Two different API surfaces. |

### Tier 2 — mechanical, additive on both sides

`main.py` (16/13, router registration), `models/__init__.py` (29/26,
exports), `App.tsx` (81/16, routes), `AppShell.tsx` (101/26, nav),
`package.json`, `analysis/__init__.py`, `ratelimit.py`, `models/user.py`,
`routers/auth.py`, `schemas/auth.py`, `routers/comments.py`,
`routers/raw_files.py`, `routers/spectra.py`, plus the CSS and page files.

### Tier 3 — docs, resolve by union

`README.md` (201/80), `raman-platform-architecture-v2.md` (46/810).

### Notably *not* conflicting

`backend/app/config.py` and `backend/app/ingestion/llm_fallback.py` both
**auto-merge cleanly**. Track A's OpenRouter work is therefore almost
entirely portable — `llm_providers.py` is a new file, config merges, and
only `jobs.py` needs real attention.

---

## 4. Tests

Track A ships 60 test files, Track B 51.

**Ten files share a name but differ in content** — this is where a careless
merge silently drops coverage:

`test_auth.py` (565/543), `test_spectrum_data.py` (505/161),
`test_search.py` (359/340), `test_processing_api.py` (225/314),
`test_ingestion_api.py` (295/322), `test_llm_fallback.py` (229/190),
`test_models_smoke.py` (167/173), `test_doi_lookup.py` (152/158),
`test_comments.py` (123/124), `test_fork.py` (132/133).

`test_spectrum_data.py` is the widest gap (A has 344 more lines).

**One path-type collision:** Track A has a `backend/tests/test_analysis/`
package; Track B has a `backend/tests/test_analysis.py` module. These
cannot both be imported cleanly — one must be renamed.

---

## 5. Neither suite was run

Stated plainly: this comparison is structural. Track A's files are not on
disk, and Track B needs a database plus a dependency install that this
sandbox blocks. **Nothing here should be read as "Track A passes" or
"Track B passes."** Track A's 633 passing tests were real on 2026-08-25 and
say nothing about today. Track B has never been run here at all.

`make check-llm` — the one real OpenRouter call — is still unrun.

---

## 6. Recommendation

**Merge them; do not pick a winner.** The evidence for this is the schema:
disjoint tables, disjoint columns, one shared table with non-overlapping
additions. That is what two complementary layers look like, not two rival
implementations. Discarding either track throws away ~20,000 lines to avoid
30 conflicted files, most of them mechanical.

Suggested order:

1. Branch `integration/merge-tracks` from **`replit/aug26-snapshot`** — it
   is what is on disk and what the Replit deployment currently runs, so
   this is the least disruptive base.
2. Merge `feature/mvp-toolbox-social` into it.
3. Resolve the six Tier-1 files by hand. Default rule: **prefer B for
   ingestion/provenance/analysis internals, prefer A for the social,
   citation and profile surface.** `jobs.py` is the one file needing real care
   — port A's header-trim regex onto B's rewritten job flow rather than
   taking either side wholesale.
4. `alembic merge` the two heads.
5. Union the ten divergent test files; rename one side of the
   `test_analysis` package/module collision.
6. Only then run both suites and `make check-llm`.

This is a recommendation, not a decision — the layering call is yours.

---

## 7. Housekeeping

- The snapshot commit includes `artifacts/` (1.0 MB of design-review
  mockups and a `package-lock.json`). It was untracked and equally at risk,
  so it went in rather than being risked. Prune it in a follow-up commit if
  unwanted.
- This repository lives inside a OneDrive-synced path. A `.git` directory
  under active cloud sync is how one track ended up silently overwriting
  the other's files on disk. Worth moving the repo outside OneDrive and
  relying on `origin` for backup.
- Neither snapshot has been pushed. `origin` still has only `main` and
  `worktree-ramanhub-scaffold`.
