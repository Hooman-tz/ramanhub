# Spectra Insight Decision Register

This register records architectural choices that shape the product across the
private workspace, processing toolbox, public commons, and community layer.
It complements the delivery roadmap in
`raman-platform-architecture-v2.md`.

## Decision status

- **Accepted** — agreed constraint for implementation.
- **Provisional** — recommended default; confirm before the affected milestone.
- **Open** — requires a product-owner decision.

| ID | Decision | Accountable role | Status | Direction and rationale | Revisit by |
| --- | --- | --- | --- | --- | --- |
| ADR-001 | Start with Raman only | Product owner + scientific lead | Accepted | Raman is the operational modality. NMR and mass spectrometry require independently accepted data, metadata, QC, parser, algorithm, and discovery contracts. | Before any new modality work |
| ADR-002 | Preserve immutable raw data | Technical lead | Accepted | Original bytes are the archival source; metadata and processing corrections create linked revisions rather than overwrite history. | Never, except for legal deletion policy |
| ADR-003 | Use versioned processing ledgers | Technical lead + scientific lead | Accepted | Every processing step records algorithm version and parameters so derived outputs are replayable. | When adding analysis artifacts |
| ADR-004 | Separate scientific search from social ranking | Product owner + scientific lead | Accepted | Objective metadata, quality, provenance, and validated similarity determine scientific discovery; reactions and trends belong only in community views. **Amendment (2026-08-29):** engagement (`app.ranking` — log-compressed, time-decayed votes/shares) ranks `/feed` and `/trending` only. `app/routers/search.py` must never import `app.ranking`; a change that "reconciles" the two is a regression, not a cleanup. | Never |
| ADR-005 | Canonical Raman data contract | Scientific lead + technical lead | Provisional | Use an ordered 1-D wavenumber/intensity representation with explicit units, canonicalization version, quality flags, and preserved original source. | Before Stage 1 implementation |
| ADR-006 | Metadata completeness | Scientific lead + technical lead | Provisional | Validate an active modality profile at confirmation and publication; preserve unknown source fields separately. Required Raman acquisition/sample fields must be ratified with domain experts. | Before Stage 1 implementation |
| ADR-007 | Google, GitHub, and ORCID identity | Product owner + technical lead | Accepted | **Decided 2026-08-29:** the beta ships three OAuth sign-in providers — Google, GitHub, and ORCID — behind an `auth_identities` table (`(provider, provider_subject)` unique). `resolve_or_create_user` links a new provider to an existing account by verified email; ORCID sign-in is enabled because linking is now well-defined. `users.google_sub`/`users.email` are nullable (ORCID may release neither). Email + password sign-in is deferred post-beta and is an additive change (a `password_hash` provider row), not an identity-model migration. | Recovery/merge UX for a user with multiple identities; before opening email+password |
| ADR-008 | DOI trust label | Scientific lead + technical lead | Provisional | A DOI becomes verified only after resolver-backed metadata is persisted and a defined validation policy passes. A user-entered string alone is a citation claim, not evidence. | Before Stage 2 implementation |
| ADR-009 | AI-assisted parsing boundary | Technical lead | Accepted | Try deterministic parsers first. AI returns schema-validated metadata or declarative mapping suggestions; never execute arbitrary generated code against production data. | Before adding formats beyond current parsers |
| ADR-010 | Durable job boundary | Technical lead + operations owner | Provisional | In-process jobs are for development only. Public beta and paid workloads require durable, idempotent jobs with retries, cancellation, and visibility checks. | Before Stage 1 beta invitation |
| ADR-011 | Private data enforcement | Technical lead | Open | Choose PostgreSQL RLS with a non-owner app role or a mandatory central policy layer backed by exhaustive regression tests. Object storage remains private in either case. | Before public beta |
| ADR-012 | Similarity search evolution | Scientific lead + technical lead | Provisional | Begin with quality- and overlap-gated Raman comparison; persist versioned feature vectors and only add indexing after relevance/latency measurements justify it. | Before Stage 4 implementation |
| ADR-013 | Local and hosted compute | Product owner + technical lead + operations owner | Provisional | Local execution is the free heavy-workload path; hosted execution is a paid, quota-governed equivalent of the same analysis contract. | Before Stage 4 implementation |
| ADR-014 | Domain layout | Product owner + technical lead | Provisional | Use `spectra-in.site` for product identity and `raman.spectra-in.site`, `nmr.spectra-in.site`, and `ms.spectra-in.site` for modality applications; maintain one stable API and public-ID namespace. | Before Stage 2 public citations |
| ADR-015 | Community moderation | Product owner | Open | Choose moderation roles, reporting handling, retention/deletion, appeal process, and acceptable-use rules before enabling public posts or comments at scale. | Before Stage 3 implementation |
| ADR-016 | Launch readiness | Product owner + operations owner | Accepted | No public announcement until private-access tests, durable jobs, publication gates, legal policies, tested backups, observability, and domain/OAuth configuration are complete. | Before launch |
| ADR-017 | Public API compatibility | Technical lead | Provisional | Introduce a versioned public API before external clients, local workers, or modality applications rely on it. Use documented deprecation windows for breaking changes. | Before Stage 2 implementation |

## Decision process

When an Open or Provisional item is decided:

1. Record the final choice, owner, and date in this document.
2. Update the architecture roadmap if the decision changes a milestone or
   launch gate.
3. Create or revise the implementation task that enforces the decision.
4. Add tests that prove the chosen safety or scientific constraint.
