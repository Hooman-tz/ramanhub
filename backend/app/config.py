"""Application settings, read from environment variables (.env in local dev).

Every field name below is a contract other modules/agents depend on — do not
rename without coordinating.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # General
    ENVIRONMENT: str = "development"

    # Database
    DATABASE_URL: str = "postgresql+psycopg://raman:changeme@localhost:5432/ramanhub"

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

    # LLM (ingestion parsing fallback)
    ANTHROPIC_API_KEY: str = ""

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
