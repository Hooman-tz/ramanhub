"""Application settings, read from environment variables (.env in local dev).

Every field name below is a contract other modules/agents depend on — do not
rename without coordinating.
"""
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Anchored to the repo root (three levels up from this file:
# backend/app/config.py -> backend/app -> backend -> repo root) rather than
# left as a bare ".env". pydantic-settings resolves a relative env_file
# against the process's CWD at import time, and the README's documented
# fast-iteration workflow runs uvicorn with `backend/` as CWD while `.env`
# lives at the repo root (`cp .env.example .env` in step 1) — a bare
# relative path there silently reads no secrets at all in exactly the
# setup most local dev actually uses. Real environment variables (e.g. from
# docker-compose's `env_file:`) still take priority over this file, per
# pydantic-settings' normal source ordering, so this only changes the
# fallback lookup, not anything already working under docker.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Public alias — other modules (e.g. the local storage backend) that need a
# CWD-independent anchor should use this rather than re-deriving it.
REPO_ROOT = _REPO_ROOT


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # General
    ENVIRONMENT: str = "development"

    # Database
    DATABASE_URL: str = "postgresql+psycopg://raman:changeme@localhost:5432/ramanhub"

    @field_validator("DATABASE_URL")
    @classmethod
    def _normalize_db_scheme(cls, v: str) -> str:
        """Managed-Postgres providers (Render, Railway, Heroku-style) hand out
        `postgres://` or `postgresql://` URLs. Bare `postgresql://` makes
        SQLAlchemy pick the psycopg2 driver — not installed here (we ship
        psycopg 3) — so normalize both to the explicit psycopg3 dialect."""
        for prefix in ("postgres://", "postgresql://"):
            if v.startswith(prefix):
                return "postgresql+psycopg://" + v[len(prefix):]
        return v

    # Storage backend: "s3" (MinIO locally, Cloudflare R2 in prod) or
    # "local" (plain files under STORAGE_LOCAL_DIR — dev without Docker,
    # never production). See app/storage/s3_client.py.
    STORAGE_BACKEND: str = "s3"
    # Relative paths resolve against the repo root, same anchoring rule as
    # the .env file itself.
    STORAGE_LOCAL_DIR: str = "storage-data"

    # Object storage (S3-compatible — Cloudflare R2 in prod, minio/localstack in dev)
    S3_ENDPOINT_URL: str = "http://localhost:9000"
    S3_ACCESS_KEY_ID: str = "minioadmin"
    S3_SECRET_ACCESS_KEY: str = "minioadmin"
    S3_BUCKET_RAW: str = "raw-spectra"
    S3_BUCKET_PROCESSED: str = "processed-spectra"
    S3_REGION: str = "auto"

    # Google OAuth
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/auth/callback"

    # JWT / auth
    JWT_SECRET: str = "change-me-to-a-long-random-string"
    JWT_EXPIRES_HOURS: int = 24

    # LLM (ingestion parsing fallback) -------------------------------------
    #
    # Two providers are supported. `LLM_PROVIDER` selects; "auto" (the
    # default) picks OpenRouter when its key is present and falls back to
    # Anthropic otherwise, so setting a single key is enough to get a
    # working parser with no further configuration.
    LLM_PROVIDER: str = "auto"  # auto | openrouter | anthropic

    ANTHROPIC_API_KEY: str = ""

    # `OPENROUTER` is accepted as an alias for the canonical name because
    # that is what already exists in some local .env files. Aliasing costs
    # nothing and avoids a silent "parser does nothing" failure whose cause
    # is invisible — an unread key looks exactly like an unset one.
    OPENROUTER_API_KEY: str = Field(
        "", validation_alias=AliasChoices("OPENROUTER_API_KEY", "OPENROUTER")
    )
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    # Open-weights and cheap by default. Header extraction is a small,
    # tightly-constrained tool call over a few hundred bytes (see
    # LLM_HEADER_MAX_CHARS), and results are cached by header hash, so
    # frontier-model headroom buys very little here.
    #
    # Every id here was checked with a REAL forced tool call, not read off
    # the catalogue. Two separate lessons are baked into that sentence:
    #
    #   1. The slug must exist. An earlier version shipped three plausible-
    #      looking names (qwen/qwen3-flash, qwen/qwen-turbo,
    #      mistralai/mistral-small-3.2-24b-instruct) and not one was real.
    #   2. Existing is not enough. /models advertises `tools` support for
    #      the whole Qwen *flash* tier, but NOT ONE of qwen3.5-flash,
    #      qwen3.6-flash, qwen3.7-flash or qwen3.8-flash will accept a
    #      forced `tool_choice` — every one returns HTTP 404 "No endpoints
    #      found that support the provided 'tool_choice' value". The flag in
    #      the catalogue means "can be given tools", not "can be forced to
    #      call one", and header extraction depends on forcing.
    #
    # So: `make check-llm ARGS='--list'` tells you what exists; only
    # `make check-llm ARGS='--model <slug>'` tells you what works.
    #
    # Chosen on PASS RATE over 5 identical runs against the real Horiba
    # header, not on one lucky call. Cheap small models are erratic here,
    # and a single green run says almost nothing:
    #
    #     qwen/qwen3.5-27b     5/5   $0.00126/call
    #     qwen/qwen3.8-27b     3/5   $0.00206/call
    #     qwen/qwen3.5-9b      2/5   $0.00012/call
    #     z-ai/glm-5.3-flash   0/5   $0.00020/call
    #
    # glm-5.3-flash passed the first time it was tried and then failed five
    # straight; 9b did the reverse. Re-measure with several runs before
    # swapping this, and treat one success as noise.
    #
    # Note 5 runs is a small sample — 5/5 is good evidence, not a guarantee.
    OPENROUTER_MODEL: str = "qwen/qwen3.5-27b"
    # Comma-separated. Passed to OpenRouter's own `models` routing array, so
    # a provider outage, a model that refuses the tool call, OR A SLUG THAT
    # NO LONGER EXISTS falls through rather than failing the upload. That
    # last case is why this is a chain and not a single name: model slugs get
    # renamed and retired, and a hardcoded one fails inside a background
    # ingestion job where nobody sees it. `make check-llm` asks OpenRouter
    # what it actually serves today.
    #
    # Worth being precise about what this chain can and cannot save you
    # from. OpenRouter falls through on HARD failures — an outage, a
    # retired slug, an endpoint that refuses forced tool_choice. It does
    # NOT fall through when a model returns confident nonsense, because a
    # schema-valid wrong answer is a success as far as HTTP is concerned.
    # So the chain buys availability, not accuracy; accuracy comes from the
    # primary being reliable, which is why it is picked on pass rate above.
    #
    # Kept to one entry, from the same family but a different size. Models
    # that measured below 5/5 are deliberately absent: promoting a 0/5 or
    # 2/5 model on an outage would turn "upload failed, enter metadata by
    # hand" into "upload silently recorded wrong instrument settings",
    # which is far worse for a spectral database.
    OPENROUTER_FALLBACK_MODELS: str = "qwen/qwen3.8-27b"

    # Hard ceiling on the header text handed to the model. The extractor
    # already stops at the first numeric data line; this is the backstop for
    # formats where that heuristic finds no data rows at all (e.g. a binary
    # header decoded to mojibake). Small on purpose — the real headers in
    # sample-data/ are under 250 bytes.
    LLM_HEADER_MAX_CHARS: int = 4000

    # Wall-clock ceiling on a single LLM HTTP call. Kept below
    # INGESTION_PARSE_TIMEOUT_SECONDS so the inner call fails with a useful
    # message before the outer job timeout fires with a generic one.
    LLM_REQUEST_TIMEOUT_SECONDS: int = 20

    # URLs
    FRONTEND_URL: str = "http://localhost:5173"
    BACKEND_URL: str = "http://localhost:8000"

    # Uploads
    MAX_UPLOAD_SIZE_MB: int = 50

    # Ingestion — wall-clock timeout around the parsing step (vendor parser
    # or LLM fallback), so a malformed/adversarial file can't hang the
    # background job indefinitely. See app/ingestion/jobs.py.
    INGESTION_PARSE_TIMEOUT_SECONDS: int = 30

    # Error tracking (Module 5). Empty by default — a true no-op until a
    # real Sentry project DSN is set (see docs/OPERATIONS.md).
    SENTRY_DSN: str = ""


settings = Settings()
