# Deploy the backend — Oracle free Micro + Neon + R2

Runs the RamanHub API on a **free Oracle Cloud `VM.Standard.E2.1.Micro`**
(1 GB RAM, x86_64, always-on). The 1 GB budget is met by keeping state and
heavy work off the box:

| Concern | Where it lives |
| --- | --- |
| Postgres | **Neon** (free managed PG) — `DATABASE_URL` in `.env` |
| Backend image build | **GitHub Actions → GHCR** — the VM only `docker compose pull`s |
| Object storage | **Cloudflare R2** (free) — `S3_*` in `.env` |
| API + ingestion worker + TLS proxy | the VM (`docker compose.prod.yml`) |

So the VM is stateless: an upgrade later = boot a bigger box, `pull`, `up -d`,
repoint DNS. ~15 min, no data migration.

Files: `docker-compose.prod.yml` (repo root), `infra/prod/Caddyfile`,
`infra/prod/.env.prod.example`, `.github/workflows/backend-image.yml`.

---

## 0. One-time: build + publish the backend image

`.github/workflows/backend-image.yml` builds `backend/` and pushes
`ghcr.io/<owner>/ramanhub-backend` on every push to `main` that touches
`backend/**` (also `workflow_dispatch`).

After the first green run, make the package pullable without auth:
**GitHub → your avatar → Packages → `ramanhub-backend` → Package settings →
Change visibility → Public.**
(Private is fine too — then run `docker login ghcr.io` on the VM with a PAT
that has `read:packages`.)

## 1. Neon (database)

Project already created: `gentle-mountain-25061060`, branch `production`.
Grab the **pooled** connection string — console → *Connection string*, or:

```bash
npm i -g neon@latest && neon login
neon connection-string production --project-id gentle-mountain-25061060 --pooled
```

Put it in `.env` as `DATABASE_URL` verbatim (keep `?sslmode=require`).
Do **not** run `neon deploy` / `neon config` — schema is owned by Alembic,
run from the container in step 6.

## 2. Cloudflare R2 (object storage)

1. Cloudflare dashboard → **R2** → create buckets `raw-spectra`,
   `processed-spectra`, `figures`.
2. **Manage R2 API Tokens → Create API token**, permission **Object Read &
   Write**.
3. Into `.env`: `S3_ENDPOINT_URL=https://<ACCOUNT_ID>.r2.cloudflarestorage.com`,
   `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`. Keep `S3_REGION=auto` and
   `STORAGE_BACKEND=s3`.

## 3. DNS + cloud firewall

- **Cloudflare DNS:** `A` record `api` → **`147.5.111.61`**, **grey cloud
  (DNS only)** — Caddy needs a direct route for the ACME challenge.
- **Oracle VCN security list:** Networking → your VCN → Security Lists →
  default → add **Ingress** rules, source `0.0.0.0/0`, TCP, dest ports **80**
  and **443**. (The VM's own `iptables` is already open for these.)

## 4. Prepare the VM

SSH in (`ssh -i ~/.ssh/oracle.key ubuntu@147.5.111.61`). Already done during
setup: 4 GB swap, host firewall for 80/443, Docker + compose + git.

```bash
git clone https://github.com/Hooman-tz/ramanhub.git
cd ramanhub
cp .env.example .env
```

Edit `.env` — overlay the values from `infra/prod/.env.prod.example`:

- `DATABASE_URL` (Neon, step 1)
- `S3_ENDPOINT_URL` / `S3_ACCESS_KEY_ID` / `S3_SECRET_ACCESS_KEY` (step 2)
- `API_DOMAIN=api.spectra-in.site`, `ACME_EMAIL=<you>`
- `FRONTEND_URL=https://raman.spectra-in.site`,
  `BACKEND_URL=https://api.spectra-in.site`,
  `COOKIE_DOMAIN=.spectra-in.site`
- `JWT_SECRET` — `openssl rand -hex 32`
- OAuth client ids/secrets for the providers you enable, `*_REDIRECT_URI` on
  the `api.` host
- `BACKEND_IMAGE` — leave default unless pinning a `:sha-` tag

## 5. Bring it up

```bash
docker compose -f docker-compose.prod.yml --env-file .env pull
docker compose -f docker-compose.prod.yml --env-file .env up -d
docker compose -f docker-compose.prod.yml logs -f caddy      # watch the cert issue
```

## 6. Migrations + seed (once, and after every schema change)

```bash
docker compose -f docker-compose.prod.yml run --rm backend uv run alembic upgrade head
docker compose -f docker-compose.prod.yml run --rm backend uv run python -m app.seed.seed_data
```

`seed_data` is idempotent and **required** — it creates licenses, metadata
field definitions and ledger step definitions. Without it `GET /licenses` is
empty and publishing a finding 422s.

## 7. Verify

```bash
curl https://api.spectra-in.site/health
```

The web app's `API_URL` on Vercel already points here, so sign-in should work
end to end once the cert is live.

---

## Operating it

**Deploy a new backend version** (after CI publishes a new image):

```bash
cd ~/ramanhub && git pull        # for compose/Caddyfile changes
docker compose -f docker-compose.prod.yml --env-file .env pull
docker compose -f docker-compose.prod.yml --env-file .env up -d
docker compose -f docker-compose.prod.yml run --rm backend uv run alembic upgrade head
```

**Logs:** `docker compose -f docker-compose.prod.yml logs -f backend ingestion-worker`

**Memory pressure** (1 GB box): `free -m`, `docker stats --no-stream`. If the
worker gets OOM-killed under load, that's the upgrade signal — move to a
bigger VM (Hetzner CX22 ~€3.79/mo, or a free Oracle A1 if capacity appears).
Because the box is stateless the move is just `pull` + `up -d` + DNS.

**Neon** handles its own backups (point-in-time restore on the free tier).
Nothing to cron on the VM.

## When you outgrow the Micro

Re-add a local `postgres` service (copy from `docker-compose.yml`) and a
`build:` for the backend, or keep Neon and just resize the VM. Neon +
`pg_dump`/restore is the migration path if you ever move the DB in-house.
