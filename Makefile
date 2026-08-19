.PHONY: up down logs migrate seed test lint

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

test:
	cd backend && uv run pytest

lint:
	cd backend && uv run ruff check app/
