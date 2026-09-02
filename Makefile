.PHONY: up down logs migrate seed seed-demo seed-scenarios import-journals worker test lint

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
