# Naming audit — option, label, and identifier names

**Status:** assessment + recommendations. **Nothing here is applied.** Each item
says where it lives, what's wrong, the fix, and the blast radius. Work the tiers
in order.

## Purpose & method

Every name a user reads or a contract exposes is judged against four rules:

1. **One concept, one word.** The same thing must not be called three names in
   three places.
2. **Matches the mental model.** A bench scientist's word beats an
   implementation word (`spectrum`, not `raw_file`; `step`, not `algorithm spec`).
3. **An action label is a verb.** Buttons say what happens (`Reset`, `Repost`),
   not what the thing is.
4. **Casing is consistent per surface.** Nav and section rails are Title Case;
   helper text and inline chips are sentence case; nothing user-facing is
   `lowercase` just because the enum value is.

**Tiers by blast radius**

| Tier | Scope | Touches | Safe to ship |
| --- | --- | --- | --- |
| 1 | UI strings only | `apps/web/**` copy | Yes — no contract change |
| 2 | User-visible API values | `apps/web` + `packages/api-client` + maybe a router `Literal` | With an api-client version bump |
| 3 | Model / enum / router / migration names | `backend/**` + Alembic + tests + api-client | At the Go rewrite (CLAUDE.md: backend → Go post-beta) — that's the natural cut line |

---

## Canonical glossary — decide these first

The write-up entity is the worst offender. It is called all of:

| Term | Where |
| --- | --- |
| **finding** | `backend/app/models/finding.py`, `/v1/findings`, accession `RH-F-`, `apps/web` `Finding` type |
| **post** | `nav.tsx` "New post", `compose-fab.tsx`, profile "Posts" section, `/` feed |
| **note** | `composer.tsx` "post a **note** to the feed", `postNote()` in `packages/api-client` |

**Recommendation:** two words, each with a clear job — and delete the third.

- **finding** = the citable noun. Keep it on the detail page (`/findings/[id]`),
  the accession, the API path, the DB. It is the thing that gets a DOI.
- **post** = the feed verb and the feed-surface noun ("New post", "Posts",
  "Nothing here yet — be the first to post"). A post *is* a finding; the word
  just changes with the surface, the way "paper" and "publication" coexist.
- **note** → retire. `postNote()` becomes `quickPost()` or folds into
  `createFinding({ publish: true })`.

Second glossary fix: **upvote** vs **vote**. `finding-actions.tsx` aria-labels
say "Vote"; the icon is `ArrowBigUp`; the API field is `vote_count`; there is no
downvote. Pick **upvote** everywhere (label, aria-label, helper) and keep
`vote_count` as the field name (a count of upvotes).

Third: **DOI-verified** vs **DOI-linked** vs **doi_linked** vs **doi_verified**.
Feed card says "DOI-linked", profile stat is `doi_linked`, backend trust tier is
`doi_verified`. Pick **DOI-verified** for every user-facing string (the backend
only claims "a DOI is attached and resolved", which *is* verification of
existence, not of content).

---

## Tier 1 — UI strings only (safe, no contract change)

All paths under `apps/web/src/`.

| Area | File | Current | Recommended | Why |
| --- | --- | --- | --- | --- |
| Feed tabs | `components/feed-view.tsx` | `discover` / `following` (rendered lowercase) | `Discover` / `Following` | Every other nav in the app is Title Case; only these are lowercase because the internal `Tab` type is. |
| Profile section | `components/profile/profile-shell.tsx` (`OWNER_SECTIONS`) | `Library` | `Spectra` | The tab is every spectrum the user owns in any state. The workbench's own left pane already calls the same list "My spectra". "Library" implies curation that isn't there. |
| Profile section | same | `Workbench` | keep | Accurate term of art; the 3-pane build screen genuinely is a workbench. |
| Workbench | `components/profile/workbench.tsx` | `Tools` (palette heading) | `Steps` | Items in the palette become numbered pipeline *steps* two inches to the right; calling them "Tools" then "1. …" is two names for one thing. |
| Workbench | same | `Reset to raw` | `Reset` | The Raw / Processed toggle right above it already names the target state. |
| Workbench | same | `Save as routine` / `Load routine` | keep | "Routine" is the right word and is used consistently here. |
| Workbench empty state | same | "No spectra yet — upload one to start processing." | "No spectra yet. Add one from your library to start." | There is no upload affordance on this screen; the copy sends users somewhere that doesn't exist. (Until an upload UI exists — see below.) |
| Library filters | `components/profile/profile-tabs.tsx` | `Material` / `Excitation nm` / `Min SNR` | `Material` / `Excitation (nm)` / `Min SNR` | Unit belongs in parentheses, matches the workbench's `Min SNR` styling. |
| Library readiness badge | same (`ReadinessBadge`) | `Ready` / `Blocked` / `Needs review` | `Publishable` / `Quality issue` / `Unreviewed` | The field behind it is `publish_ready`; "Ready" is ambiguous (ready for what?). "Blocked" sounds like a moderation action; it's a QC failure. |
| Composer | `components/composer.tsx` | `Attach spectra` / `Attach figure` | `New finding with spectra` / `New finding with a figure` | Both buttons call `createFinding` and navigate away — they start a draft, they do not attach anything to the current note. |
| Composer | same | "Share with the community" / "Post a note, or start a finding with visuals." | "Post to the feed" / "Share a quick note, or start a finding with data and figures." | "with visuals" is vague; the distinction is data/figures vs plain text. |
| Composer (guest) | same | "Sign in to post a note to the feed." | "Sign in to post to the feed." | Drops the retired word "note". |
| Finding actions | `components/finding-actions.tsx` | `Vote for this finding` / `Remove your vote` (aria) | `Upvote` / `Remove upvote` | See glossary. |
| Finding actions | same | `Share this finding` / `Undo share` (aria); icon `Repeat2` | `Repost` / `Undo repost` | The model (`Share` with a `comment` quote field) and the icon are a repost. "Share" collides with OS share sheets and with "Share with the community" in the composer. |
| Finding actions (guest) | same | "Sign in to vote or share" | "Sign in to upvote or repost" | Consistency with the two above. |
| Feed card | `components/feed-card.tsx` | `votes` (sr-only) | `upvotes` | Match. |
| Feed card | same | `DOI-linked` pill | `DOI-verified` | Glossary. |
| Feed card | same | kind tag `finding` / `spectrum` (uppercased) | keep values, but render `Finding` / `Spectrum` (Title Case, not SHOUTING) | Uppercasing user content reads as an error state. |
| Finding detail | `app/findings/[id]/page.tsx` | `· {finding.state}` → shows bare `draft` / `published` | `Draft` / `Published` badge | Raw enum value leaking to the page. |
| Findings thread | same | section heading `Thread` | `Updates` or `Log` | "Thread" implies a discussion; this is the author's append-only progress log. The *discussion* is the Comments section below it. |
| Comments | `components/finding-comments.tsx` | `Add a comment…` / "start the discussion" | keep | Good as-is. |
| Image uploader | `components/finding-image-uploader.tsx` | `Upload as` → `Figure` / `Graphical abstract` | keep | Accurate. |
| Account menu | `components/nav.tsx` | `My profile` | keep | Fine. |
| Settings | `app/settings/page.tsx` | card titles `Profile` / `Identity` / `Data` | `Profile` / `Identity` / `Your data` | "Data" alone reads like a data-browsing screen; this card is export/delete. |
| Settings / onboarding | `app/settings/page.tsx`, `app/onboarding/page.tsx` | `Make my profile public` | keep | Clear. |
| Contribution graph | `components/profile/contribution-graph.tsx` | "{n} contribution(s) in the last year" | keep | Matches the GitHub mental model it borrows. |
| Pin button | `components/profile/pin-button.tsx` | `Pin to profile` / `Pinned to profile` / `Pin limit reached (4)` | keep | Clear and honest about the cap. |

---

## Tier 2 — user-visible API values

These are strings the client sends or displays. Changing them is an api-client
change and sometimes a one-line router `Literal` edit; **no migration** unless
noted.

| Value | Where | Current | Recommended | Notes |
| --- | --- | --- | --- | --- |
| Feed filter | `backend/app/routers/feed.py` `filter: Literal["all","following"]` | `all` surfaced in UI as the "discover" tab | Rename the tab label to **Discover** (Tier 1) but also rename the value `all` → `discover` for symmetry with `following` | Router `Literal` + `packages/api-client` `FeedParams` + `feed-view.tsx` mapping. |
| Feed `kind` | `feed.py` request `Literal["all","findings","spectra"]` vs response `FeedItem.kind: Literal["finding","spectrum"]` | plural in the request, singular in the response | Use singular everywhere: request `Literal["all","finding","spectrum"]` | Removes a plural/singular mismatch a client dev hits immediately. |
| Trust tier | `feed.py` + `search.py` `Literal["doi_verified","community"]` | `doi_verified` / `community` | `with_doi` / `all` — or keep `doi_verified` and drop `community` (the opposite of "has a DOI" is "everything", not a separate class) | `community` implies a quality judgement the tier doesn't make. api-client `FeedParams` + `search` params. |
| Community post kind | `backend/app/models/social.py` `CommunityPost.kind` free string; `community.py` `Literal["announcement","dataset"]` | `announcement` | `update` | Shorter, and "research update" is what the UI calls it. Free-string column so no enum migration; a data backfill `UPDATE community_posts SET kind='update' WHERE kind='announcement'` + the `Literal`. |
| Report reason | `community.py` `Literal["spam","harassment","privacy","copyright","misinformation","other"]` | fine | keep | Standard set. |
| Finding image kind | `finding_image.py` `FINDING_IMAGE_KINDS = ("figure","graphical_abstract")` | fine | keep | Matches the UI select. |

---

## Tier 3 — model / enum / router / migration names

Do these at the Go rewrite. Each needs an Alembic migration (enum rename or
type swap), a test sweep, and an api-client type change.

| Name | File | Current | Recommended | Why |
| --- | --- | --- | --- | --- |
| `FindingEntryKind.spectra` | `backend/app/models/enums.py` | `spectra` (a plural used as one member value) | `spectrum_set` | Every other member is singular (`note`, `figure`, `peaks`). `spectra` as a value reads as "many" when it means "the member-spectra list entry". |
| `FindingEntryKind.hca` | same | present, unused | delete | HCA exists only as a finding-entry kind — there is no `hca` analysis run type (`analysis.py` is `pca` / `pca_kmeans`). Dead value in a native PG enum is a migration liability. |
| `moderation_status` | `spectrum.py`, `social.py` (`Comment`, `CommunityPost`) | free `String`, values `"visible"` / `"hidden"` by convention | a real `ModerationStatus` enum | Three tables, one convention, zero enforcement. A typo'd `"hidden "` silently un-hides. |
| Finding "embargo" | `finding.py` | `FindingState` has only `draft` / `published`; the seed and UI fake an embargo by setting `Spectrum.embargo_release_at` and leaving the finding published | add `FindingState.embargoed` **or** document that findings never embargo and drop the pretence | `Spectrum` has a real `embargoed` state; `Finding` doesn't, so "an embargoed finding" is currently just "a published finding whose spectra are embargoed". Pick one model. |
| `RawFile` vs `Spectrum` in UI | — | UI never says "raw file"; it says "spectrum". `raw_file_id` leaks into `LibrarySpectrumResult` and the workbench | keep the DB name, but never surface `raw_file` — the workbench should talk about the spectrum and its ledger, not the raw file id | Implementation noun in a user payload. |
| `AnalysisDataset` | `analysis.py` | model name `AnalysisDataset`; UI calls a grouped set of spectra a "dataset"; the Library tab (to be renamed "Spectra") is *not* this | keep `AnalysisDataset`, and in the UI always qualify: "analysis dataset" or just "dataset" in the analysis context only | Two things want the word "dataset" — the analysis input set and (loosely) the user's whole library. Reserve it for the former. |
| `ProcessingRoutine` / `ProcessingLedger` | `processing_routine.py`, `processing_ledger.py` | routine = reusable template, ledger = applied immutable record | keep both — they're good | Listed only to confirm they're *not* a problem: "routine" (saved recipe) vs "ledger" (what was actually run) is a real and useful distinction. |
| `postNote` | `packages/api-client/src/index.ts` | composite create-then-publish helper | `quickPost` | "Note" is the retired third synonym (see glossary). |
| `CommunityPost` | `social.py` | separate model from `Finding`, both called "post" somewhere in the UI | rename to `Announcement` (matches its dominant `kind`) or `Update` | Right now "post" can mean a `Finding` (feed) *or* a `CommunityPost` (community tab). One of them must give up the word; the feed one is more prominent, so `CommunityPost` yields. |

---

## Cross-cutting rules to adopt

1. **Casing:** nav / section rails / tab labels = Title Case. Chips, badges,
   helper text, empty states = sentence case. Never render a raw enum value;
   map it to a cased label.
2. **Actions are verbs:** `Reset`, `Apply`, `Repost`, `Upvote`, `Follow`,
   `Pin`. Not `Reset to raw`, not `Vote for this finding`.
3. **One synonym per concept** (see glossary): finding/post (by surface), never
   "note"; upvote, never "vote"; DOI-verified, never "DOI-linked"; repost,
   never "share".
4. **No implementation nouns in user text:** no `raw_file`, no `ledger_id`, no
   `accession` unqualified (call it "ID" or "record ID" in the UI, keep
   "accession" for docs).
5. **Buttons that navigate say so:** "New finding with spectra" starts a draft
   and leaves the page; "Attach" must mean attach-in-place or not be used.

---

## Prioritized action list

| When | Do |
| --- | --- |
| **Now** (Tier 1) | Feed tab casing; `Library` → `Spectra`; `Tools` → `Steps`; `Reset to raw` → `Reset`; readiness badges; composer "Attach" buttons; "Vote" → "Upvote"; "Share" → "Repost"; render enum-value badges cased. All are `apps/web` copy edits with no test impact. |
| **Next api-client bump** (Tier 2) | Singular `kind` in the feed request; `filter` value `all` → `discover`; decide `trust_tier` naming; `announcement` → `update` (+ data backfill). |
| **At the Go rewrite** (Tier 3) | `FindingEntryKind` cleanup (`spectra` → `spectrum_set`, drop `hca`); `moderation_status` enum; resolve the finding-embargo model; `CommunityPost` → `Announcement`; `postNote` → `quickPost`. Bundle with the schema port so there's one migration, not five. |

## Concrete before → after (the shortlist)

| # | Where | Before | After | Tier |
| --- | --- | --- | --- | --- |
| 1 | `feed-view.tsx` | `discover` / `following` | `Discover` / `Following` | 1 |
| 2 | `profile-shell.tsx` | section `Library` | section `Spectra` | 1 |
| 3 | `workbench.tsx` | palette `Tools` | `Steps` | 1 |
| 4 | `workbench.tsx` | `Reset to raw` | `Reset` | 1 |
| 5 | `profile-tabs.tsx` | `Ready` / `Blocked` / `Needs review` | `Publishable` / `Quality issue` / `Unreviewed` | 1 |
| 6 | `composer.tsx` | `Attach spectra` / `Attach figure` | `New finding with spectra` / `New finding with a figure` | 1 |
| 7 | `finding-actions.tsx` | `Share this finding` (icon `Repeat2`) | `Repost` | 1 |
| 8 | app-wide | `DOI-linked` / `doi_linked` / `doi_verified` | `DOI-verified` | 1–2 |
| 9 | `feed.py` + api-client | `filter=all` (the "discover" tab) | `filter=discover` | 2 |
| 10 | `feed.py` | request `kind` plural, response `kind` singular | singular both | 2 |
| 11 | `social.py` + `community.py` | `CommunityPost.kind = "announcement"` | `"update"` | 2/3 |
| 12 | `enums.py` | `FindingEntryKind.spectra`; unused `hca` | `spectrum_set`; drop `hca` | 3 |
| 13 | `enums.py` / `spectrum.py` / `social.py` | free-string `moderation_status` | `ModerationStatus` enum | 3 |
| 14 | `api-client` | `postNote()` | `quickPost()` | 3 |
