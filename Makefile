.PHONY: up down logs migrate seed seed-demo test lint

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

test:
	cd backend && uv run pytest

# Live check of the OpenRouter setup: lists the models OpenRouter actually
# serves, then does one real forced tool call on a real vendor header.
#   make check-llm                     full check
#   make check-llm ARGS='--list'       just list qwen/flash models
#   make check-llm ARGS='--model qwen/qwen3-flash'
check-llm:
	uv run --project backend python scripts/check_llm.py $(ARGS)

lint:
	cd backend && uv run ruff check app/
