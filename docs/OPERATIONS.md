# Operations

Pre-launch hardening notes for RamanHub (Module 5: Security, Logging &
Operations). This covers the operational setup that lives outside the
application code itself — DB permissions, backups, error tracking, and
dependency updates.

## 1. Least-privilege database user

**Local dev** currently uses a single broad Postgres role (`raman`, from
`docker-compose.yml` / `.env.example`'s `POSTGRES_USER`) that owns the
database outright — fine for a throwaway local container, but the app
should never connect as a superuser or database owner in any environment
that holds real user data.

For staging/production, create a dedicated, least-privilege application
role that can only do what the app actually needs — read/write rows and use
sequences/extensions already set up by a migration step, nothing else
(no `CREATEDB`, `CREATEROLE`, `SUPERUSER`, and no `DROP`/`ALTER` on
objects it doesn't own):

```sql
-- Run once, as a superuser/owner, against the target database.

-- 1. A separate *migration* role that owns the schema and runs Alembic
--    migrations (CREATE/ALTER/DROP TABLE etc.) — this is the role CI/CD or
--    an operator uses for `alembic upgrade head`, never the app's runtime
--    connection.
CREATE ROLE ramanhub_migrator LOGIN PASSWORD '<strong-random-password>';
GRANT ALL PRIVILEGES ON DATABASE ramanhub TO ramanhub_migrator;

-- 2. The app's runtime role — this is what DATABASE_URL points at in
--    staging/prod. It can read/write data in existing tables and use
--    sequences (for SERIAL/IDENTITY columns) and the pgcrypto extension
--    (gen_random_uuid()), but cannot create, alter, or drop schema objects,
--    and is not a superuser.
CREATE ROLE ramanhub_app LOGIN PASSWORD '<different-strong-random-password>';
GRANT CONNECT ON DATABASE ramanhub TO ramanhub_app;
GRANT USAGE ON SCHEMA public TO ramanhub_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO ramanhub_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO ramanhub_app;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO ramanhub_app;

-- Keep future tables/sequences covered automatically, so a migration adding
-- a table doesn't silently need a manual grant afterwards.
ALTER DEFAULT PRIVILEGES FOR ROLE ramanhub_migrator IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ramanhub_app;
ALTER DEFAULT PRIVILEGES FOR ROLE ramanhub_migrator IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO ramanhub_app;

-- Row-Level Access Control note: the app enforces Draft/embargoed-spectrum
-- visibility at the query layer (SQLAlchemy filters keyed off owner_id /
-- draft state), not via Postgres RLS policies, per the current codebase.
-- If/when RLS policies are added, `ramanhub_app` (not a superuser/owner
-- role, which bypasses RLS by default) must be the role they're written
-- against, or they'll silently do nothing.
```

Point `DATABASE_URL` (staging/prod) at `ramanhub_app`. Run
`alembic upgrade head` as `ramanhub_migrator` (e.g. a one-off deploy step),
never as the app's runtime connection.

Hosted Postgres providers (Railway, Render, Supabase, RDS — see "Hosting &
deployment" below) typically hand you one owner-level role by default;
creating the two roles above against that managed instance is still worth
doing rather than running the app as the provider-issued owner role.

## 2. Automated backups

**Preferred path: use the hosting provider's built-in backups.** Per
`raman-platform-architecture-v2.md`'s "HOSTING & DEPLOYMENT" section, this
project's realistic backend/Postgres hosts are Railway or Render (fast to
start, no sponsorship needed) or the Digital Research Alliance of Canada
(UBC ARC) cloud once sponsored. Railway and Render's managed Postgres both
offer automated daily backups (with point-in-time recovery on paid tiers)
with zero setup beyond enabling the option in their dashboard — this is
strictly preferable to a self-managed cron job: it's off the primary
server by construction (Module 5's "stored somewhere other than the
primary server" requirement), needs no maintenance, and survives the
backend instance itself being redeployed or destroyed.

If the Alliance/UBC ARC path is used instead (or as an off-provider
secondary copy), a `pg_dump`-based script is the fallback:

```bash
#!/usr/bin/env bash
# scripts/backup_db.sh — example only; not wired into any scheduler by this
# pass. Requires pg_dump matching (or newer than) the server's Postgres
# version, and a DATABASE_URL pointed at the *migrator* role or another role
# with SELECT on everything (a plain read replica login also works).
set -euo pipefail

TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
mkdir -p "$BACKUP_DIR"

pg_dump "$DATABASE_URL" --format=custom --file="$BACKUP_DIR/ramanhub_${TIMESTAMP}.dump"

# Upload off-box immediately — never leave the only copy on the same host as
# the primary database. Cloudflare R2 is already in use for object storage
# (see app/config.py's S3_* settings), so it's a natural, zero-extra-cost
# destination for this too.
aws s3 cp \
    "$BACKUP_DIR/ramanhub_${TIMESTAMP}.dump" \
    "s3://${S3_BACKUP_BUCKET}/db-backups/ramanhub_${TIMESTAMP}.dump" \
    --endpoint-url "$S3_ENDPOINT_URL"

# Prune anything older than 30 days, locally.
find "$BACKUP_DIR" -name 'ramanhub_*.dump' -mtime +30 -delete
```

Run via a daily cron/systemd timer if self-managing this. Restore with
`pg_restore --clean --if-exists -d "$DATABASE_URL" ramanhub_<ts>.dump`. Test
the restore path at least once before relying on it — an untested backup is
not a backup.

## 3. Sentry (error tracking)

The app calls `sentry_sdk.init(dsn=settings.SENTRY_DSN, ...)` in
`app/main.py`'s app factory, guarded by `if settings.SENTRY_DSN:` — it's a
true no-op (no import errors, no behavior change) until a DSN is set, which
is the current state (no Sentry account exists yet).

To turn it on:

1. Create a free Sentry account at <https://sentry.io> (or self-host, out of
   scope here).
2. Create a new project, platform = Python / FastAPI.
3. Copy the project's DSN from Settings → Client Keys (DSN).
4. Set the `SENTRY_DSN` environment variable in the hosting platform's
   secret manager (Railway/Render env vars, or `.env` locally for testing —
   never commit a real DSN to the repo; `.env.example` keeps the placeholder
   empty).
5. Redeploy / restart the backend. Errors raised in request handlers and
   background ingestion jobs are now captured automatically with stack
   traces and request context.

No code changes are needed beyond what's already wired — this section is
purely the account/credential setup step referenced as a PREREQUISITE in
the architecture doc.

## 4. Dependabot

Enabled via `.github/dependabot.yml` at the repo root: weekly update PRs for
the backend's Python dependencies (`pip` ecosystem, `/backend`) and the
frontend's npm dependencies (`npm` ecosystem, `/frontend`), plus GitHub
Actions workflow versions if any are added later. This needs no further
setup once the repo (with this file) is pushed to GitHub — Dependabot is
free and enabled automatically for any public repo, and for private repos
under an org/plan that includes it.
