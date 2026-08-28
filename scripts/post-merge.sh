#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT/backend"
uv sync --python 3.12 --frozen
uv run --python 3.12 alembic upgrade head

cd "$ROOT/frontend"
npm ci --no-audit --no-fund
npm run build