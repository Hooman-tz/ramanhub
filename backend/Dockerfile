# RamanHub backend — dev image, uv-managed Python/FastAPI.
FROM python:3.11-slim

# Pull the `uv` binary from Astral's distroless image instead of pip-installing
# it, so it's always the latest static build and doesn't bloat the layer.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# Copy dependency manifests first so `uv sync` is cached across rebuilds when
# only application code changes. `uv.lock` may not exist yet on a fresh
# checkout (e.g. before the first `uv lock` run) — the glob keeps this COPY
# from failing in that case.
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-install-project

# Now copy the rest of the app code and sync again to install the project
# itself (picked up from bind mount at runtime too, for hot-reload dev).
COPY . .
RUN uv sync

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
