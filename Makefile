.PHONY: up down logs migrate seed seed-demo seed-scenarios seed-library import-journals worker test lint

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

migrate:
	cd backend && uv run alembic upgrade head

seed:
	cd backend && uv run python -m app.seed.seed_data

seed-demo:
	cd backend && uv run python -m app.seed.demo_data

# 20 test personas with synthetic spectra, datasets, processing, write-ups
# and a social graph. Requires `make seed` first. `make seed-scenarios ARGS=--reset`
# drops the personas.
seed-scenarios:
	cd backend && uv run python -m app.seed.scenarios_data $(ARGS)

# Bundled open reference spectra for the Library.
#
# Default source is the Raman Open Database (CC0, ~1,133 entries, minerals +
# organics + polymers). ROD publishes no archive tarball, so --fetch walks its
# id range politely (one request at a time, resumable, skips what is already on
# disk) before importing:
#
#   make seed-library ARGS="--dir .cache/rod --fetch --limit 25"   # dry run
#   make seed-library ARGS="--dir .cache/rod --fetch"              # full ~1,133
#
# RRUFF is the deeper mineral set but its licence is UNCONFIRMED — RRUFF's own
# pages state none. Confirm in writing before running it:
#
#   make seed-library ARGS="--source rruff-unoriented-highres --dir /path/to/rruff"
#
# Requires `make seed` first (needs the licence rows). Idempotent and resumable.
seed-library:
	cd backend && uv run python -m app.seed.reference_library $(ARGS)

import-journals:
	cd backend && uv run python -m scripts.import_scimago "$(FILE)"

# Ingestion worker. `POST /raw-files` only enqueues a job — nothing parses it
# until this is running, so the upload flow needs it alongside the API.
worker:
	cd backend && uv run python -m app.ingestion.worker

test:
	cd backend && uv run pytest

lint:
	cd backend && uv run ruff check app/
