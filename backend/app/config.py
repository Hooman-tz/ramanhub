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
DEFAULT_JWT_SECRET = "change-me-to-a-long-random-string"

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
    # Author-supplied Finding images (figures, graphical abstract). Its own
    # bucket so image lifecycle/ACLs stay independent of spectrum data; for
    # the `local` backend it's just a subdirectory, no infra needed.
    S3_BUCKET_FIGURES: str = "figures"
    S3_REGION: str = "auto"

    # Google OAuth
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/auth/callback"

    # GitHub OAuth (beta sign-in provider)
    GITHUB_CLIENT_ID: str = ""
    GITHUB_CLIENT_SECRET: str = ""
    GITHUB_REDIRECT_URI: str = "http://localhost:8000/auth/github/callback"

    # ORCID serves two flows:
    #   - proof-of-control *linking* for an existing account
    #     (ORCID_REDIRECT_URI, handled by routers/orcid.py), and
    #   - application *sign-in* (ORCID_LOGIN_REDIRECT_URI, handled by
    #     routers/auth.py). Two redirect URIs so the callbacks stay on
    #     distinct paths.
    ORCID_CLIENT_ID: str = ""
    ORCID_CLIENT_SECRET: str = ""
    ORCID_REDIRECT_URI: str = "http://localhost:8000/users/me/orcid/callback"
    ORCID_LOGIN_REDIRECT_URI: str = "http://localhost:8000/auth/orcid/callback"

    # JWT / auth
    JWT_SECRET: str = DEFAULT_JWT_SECRET
    JWT_EXPIRES_HOURS: int = 24

    # LLM (ingestion header parsing + abstract enrichment) — routed through
    # OpenRouter so the operator can pick a smaller/cheaper model. An empty
    # key means LLM features are skipped, not an error. `OPENROUTER` is
    # accepted as an alias for `OPENROUTER_API_KEY`.
    OPENROUTER_API_KEY: str = Field(
        default="",
        validation_alias=AliasChoices("OPENROUTER_API_KEY", "OPENROUTER"),
    )
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    # Default model — cheap, reliable JSON. Operator overrides via env.
    OPENROUTER_MODEL: str = "openai/gpt-4o-mini"
    # Optional per-call-site overrides; empty => fall back to OPENROUTER_MODEL.
    OPENROUTER_INGESTION_MODEL: str = ""
    OPENROUTER_ENRICHMENT_MODEL: str = ""

    # URLs
    FRONTEND_URL: str = "http://localhost:5173"
    BACKEND_URL: str = "http://localhost:8000"
    # Leave empty until spectra-in.site (or a future modality domain) is
    # configured with OAuth/CORS/redirects. APIs still return canonical paths.
    PUBLIC_APP_URL: str = ""

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


def require_secure_production_settings() -> None:
    """Fail closed if a deploy accidentally uses the development JWT secret."""
    if settings.ENVIRONMENT.lower() in {"production", "prod"} and (
        settings.JWT_SECRET == DEFAULT_JWT_SECRET or len(settings.JWT_SECRET) < 32
    ):
        raise RuntimeError("JWT_SECRET must be a non-default value of at least 32 characters in production")
